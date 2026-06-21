from datetime import date, datetime, timedelta

from db_neon import get_neon_db as get_db, query_dict, query_dict_one, execute_query


REMINDER_MESSAGE = (
    "Hello {name},\n"
    "Your vehicle {vehicle} is due for service.\n"
    "Please visit Shreeji Auto Service for maintenance."
)


def _today():
    return date.today().isoformat()


def get_due_service_reminders():
    rows = query_dict("""
        SELECT
            booking_id,
            name AS customer_name,
            phone,
            vehicle,
            completed_at,
            COALESCE(NULLIF(completed_at, '')::timestamp::date, NULLIF(date, '')::date) AS last_service_date,
            (CURRENT_DATE - COALESCE(NULLIF(completed_at, '')::timestamp::date, NULLIF(date, '')::date)) AS days_passed,
            COALESCE(service_reminder_sent, 0) AS service_reminder_sent,
            reminder_sent_at,
            reminder_snooze_until
        FROM bookings
        WHERE status = 'completed'
          AND COALESCE(NULLIF(completed_at, '')::timestamp::date, NULLIF(date, '')::date) <= CURRENT_DATE - INTERVAL '90 days'
          AND COALESCE(service_reminder_sent, 0) = 0
          AND (
              reminder_snooze_until IS NULL
              OR reminder_snooze_until = ''
              OR reminder_snooze_until::date <= CURRENT_DATE
          )
        ORDER BY last_service_date ASC, customer_name ASC
    """)

    reminders = []
    for row in rows:
        item = dict(row)
        sent_at = item.get("reminder_sent_at")
        snooze_until = item.get("reminder_snooze_until")
        if sent_at:
            item["reminder_status"] = "Sent"
        elif snooze_until:
            item["reminder_status"] = f"Snoozed until {snooze_until}"
        else:
            item["reminder_status"] = "Due"
        reminders.append(item)
    return reminders


def get_due_service_reminders_local():
    from db_local import local_query

    rows = local_query("""
        SELECT booking_id,
               name AS customer_name,
               phone, vehicle, completed_at,
               COALESCE(
                   date(NULLIF(SUBSTR(completed_at,1,10),''), 'utc'),
                   date(NULLIF(SUBSTR(date,1,10),''), 'utc')
               ) AS last_service_date,
               CAST(julianday('now') - julianday(
                   COALESCE(NULLIF(SUBSTR(completed_at,1,10),''), NULLIF(SUBSTR(date,1,10),''))
               ) AS INTEGER) AS days_passed,
               COALESCE(service_reminder_sent, 0) AS service_reminder_sent,
               reminder_sent_at,
               reminder_snooze_until
        FROM cache_bookings
        WHERE status = 'completed'
          AND COALESCE(NULLIF(SUBSTR(completed_at,1,10),''), NULLIF(SUBSTR(date,1,10),'')) <= date('now', '-90 days')
          AND COALESCE(service_reminder_sent, 0) = 0
          AND (
              reminder_snooze_until IS NULL
              OR reminder_snooze_until = ''
              OR reminder_snooze_until <= date('now')
          )
        ORDER BY last_service_date ASC, customer_name ASC
    """)
    reminders = []
    for row in rows:
        item = dict(row)
        sent_at = item.get("reminder_sent_at")
        snooze_until = item.get("reminder_snooze_until")
        if sent_at:
            item["reminder_status"] = "Sent"
        elif snooze_until:
            item["reminder_status"] = f"Snoozed until {snooze_until}"
        else:
            item["reminder_status"] = "Due"
        reminders.append(item)
    return reminders


def count_due_service_reminders():
    row = query_dict_one("""
        SELECT COUNT(*) AS total
        FROM bookings
        WHERE status = 'completed'
          AND COALESCE(NULLIF(completed_at, '')::timestamp::date, NULLIF(date, '')::date) <= CURRENT_DATE - INTERVAL '90 days'
          AND COALESCE(service_reminder_sent, 0) = 0
          AND (
              reminder_snooze_until IS NULL
              OR reminder_snooze_until = ''
              OR reminder_snooze_until::date <= CURRENT_DATE
          )
    """)
    return int(row["total"] or 0) if row else 0


def count_due_service_reminders_local():
    from db_local import local_query_one

    row = local_query_one("""
        SELECT COUNT(*) AS total FROM cache_bookings
        WHERE status = 'completed'
          AND COALESCE(NULLIF(SUBSTR(completed_at,1,10),''), NULLIF(SUBSTR(date,1,10),'')) <= date('now', '-90 days')
          AND COALESCE(service_reminder_sent, 0) = 0
          AND (
              reminder_snooze_until IS NULL
              OR reminder_snooze_until = ''
              OR reminder_snooze_until <= date('now')
          )
    """)
    return int(row["total"] or 0) if row else 0


def get_service_reminder(booking_id):
    return query_dict_one("""
        SELECT booking_id, name AS customer_name, phone, vehicle, completed_at,
               COALESCE(NULLIF(completed_at, '')::timestamp::date, NULLIF(date, '')::date) AS last_service_date
        FROM bookings
        WHERE booking_id = %s AND status = 'completed'
    """, (booking_id,))


def build_service_reminder_message(reminder):
    return REMINDER_MESSAGE.format(
        name=(reminder or {}).get("customer_name", ""),
        vehicle=(reminder or {}).get("vehicle", ""),
    )


def mark_service_reminder_sent(booking_id):
    existing = query_dict_one(
        "SELECT booking_id FROM bookings WHERE booking_id = %s",
        (booking_id,),
    )
    if not existing:
        return False

    execute_query("""
        UPDATE bookings
        SET service_reminder_sent = 1,
            reminder_sent_at = %s,
            reminder_snooze_until = NULL
        WHERE booking_id = %s
    """, (datetime.now().strftime("%Y-%m-%d %H:%M"), booking_id))
    return True


def snooze_service_reminder(booking_id, days=7):
    snooze_until = (date.today() + timedelta(days=days)).isoformat()
    existing = query_dict_one(
        "SELECT booking_id FROM bookings WHERE booking_id = %s",
        (booking_id,),
    )
    if not existing:
        return False, snooze_until

    execute_query("""
        UPDATE bookings
        SET reminder_snooze_until = %s
        WHERE booking_id = %s
    """, (snooze_until, booking_id))
    return True, snooze_until
