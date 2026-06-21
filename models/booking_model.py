from db_neon import get_neon_db as get_db, query_dict, query_dict_one, execute_query
from utils.constants import ACTIVE_SLOT_STATUSES, STATUS_CHECKED_IN


BOOKING_COLUMNS = """
    booking_id, customer_id, name, phone, vehicle, brand_model,
    service, date, status, created_at, checked_in_at, completed_at, whatsapp_sent,
    actual_visit_date, is_rescheduled, msg_approved_sent, msg_rejected_sent,
    msg_checkedin_sent, msg_completed_sent, service_reminder_sent,
    reminder_sent_at, reminder_snooze_until, source
"""


def row_to_booking(row):
    booking = dict(row)
    booking["customer_id"] = booking.get("customer_id") or ""
    booking["phone"] = booking.get("phone") or ""
    booking["brand_model"] = booking.get("brand_model") or ""
    booking["whatsapp_sent"] = int(booking.get("whatsapp_sent") or 0)
    booking["actual_visit_date"] = booking.get("actual_visit_date") or ""
    booking["is_rescheduled"] = int(booking.get("is_rescheduled") or 0)
    booking["msg_approved_sent"] = int(booking.get("msg_approved_sent") or 0)
    booking["msg_rejected_sent"] = int(booking.get("msg_rejected_sent") or 0)
    booking["msg_checkedin_sent"] = int(booking.get("msg_checkedin_sent") or 0)
    booking["msg_completed_sent"] = int(booking.get("msg_completed_sent") or 0)
    booking["service_reminder_sent"] = int(booking.get("service_reminder_sent") or 0)
    booking["reminder_sent_at"] = booking.get("reminder_sent_at") or ""
    booking["reminder_snooze_until"] = booking.get("reminder_snooze_until") or ""
    booking["source"] = booking.get("source") or "customer_portal"
    booking["checked_in"] = booking.get("status") == STATUS_CHECKED_IN
    booking["is_manual"] = not bool(booking.get("customer_id"))
    return booking


def get_all_bookings():
    rows = query_dict(f"SELECT {BOOKING_COLUMNS} FROM bookings")
    return [row_to_booking(row) for row in rows]


def search_bookings(query=None, date=None, status=None):
    normalized_query = (query or "").strip().lower()
    normalized_date = (date or "").strip() or None
    normalized_status = (status or "").strip().lower() or None
    search_term = f"%{normalized_query}%"

    rows = query_dict(
        f"""
        SELECT {BOOKING_COLUMNS}
        FROM bookings
        WHERE (
            %s = '' OR
            LOWER(booking_id) LIKE %s OR
            LOWER(customer_id) LIKE %s OR
            LOWER(phone) LIKE %s OR
            LOWER(vehicle) LIKE %s
        )
        AND (%s IS NULL OR status = %s)
        AND (%s IS NULL OR date = %s)
        ORDER BY COALESCE(created_at, checked_in_at, date, '') DESC
        LIMIT 50
        """,
        (
            normalized_query,
            search_term, search_term, search_term, search_term,
            normalized_status, normalized_status,
            normalized_date, normalized_date,
        ),
    )
    return [row_to_booking(row) for row in rows]


def get_today_bookings(today_date):
    rows = query_dict(
        f"""
        SELECT {BOOKING_COLUMNS}
        FROM bookings
        WHERE date = %s OR actual_visit_date = %s
        ORDER BY COALESCE(created_at, checked_in_at, date, '') DESC
        LIMIT 50
        """,
        (today_date, today_date),
    )
    return [row_to_booking(row) for row in rows]


def get_booking_by_id(booking_id):
    row = query_dict_one(
        f"SELECT {BOOKING_COLUMNS} FROM bookings WHERE booking_id = %s",
        (booking_id,),
    )
    return row_to_booking(row) if row else None


def booking_id_exists(booking_id):
    row = query_dict_one(
        "SELECT 1 FROM bookings WHERE booking_id = %s LIMIT 1",
        (booking_id,),
    )
    return row is not None


def get_bookings_by_customer(customer_id):
    rows = query_dict(
        f"SELECT {BOOKING_COLUMNS} FROM bookings WHERE customer_id = %s",
        (customer_id,),
    )
    return [row_to_booking(row) for row in rows]


def check_duplicate_booking(phone, vehicle, date, exclude_booking_id=None):
    normalized_phone = (phone or "").strip()
    normalized_vehicle = (vehicle or "").strip().upper()
    normalized_date = (date or "").strip()

    if not normalized_phone or not normalized_vehicle or not normalized_date:
        return None

    query = f"""
        SELECT {BOOKING_COLUMNS}
        FROM bookings
        WHERE phone = %s
        AND vehicle = %s
        AND date = %s
        AND status NOT IN ('completed', 'rejected')
    """
    params = [normalized_phone, normalized_vehicle, normalized_date]

    if exclude_booking_id:
        query += " AND booking_id != %s"
        params.append(exclude_booking_id)

    query += " LIMIT 1"
    row = query_dict_one(query, params)
    return row_to_booking(row) if row else None


def create_booking(booking):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            f"""
            INSERT INTO bookings (
                booking_id, customer_id, name, phone, vehicle, brand_model,
                service, date, status, created_at, checked_in_at, completed_at, whatsapp_sent,
                actual_visit_date, is_rescheduled, msg_approved_sent, msg_rejected_sent,
                msg_checkedin_sent, msg_completed_sent, source
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                booking["booking_id"],
                booking.get("customer_id", ""),
                booking["name"],
                booking.get("phone", ""),
                booking["vehicle"],
                booking.get("brand_model", ""),
                booking["service"],
                booking["date"],
                booking["status"],
                booking.get("created_at", ""),
                booking.get("checked_in_at"),
                booking.get("completed_at"),
                int(booking.get("whatsapp_sent", 0) or 0),
                booking.get("actual_visit_date"),
                int(booking.get("is_rescheduled", 0) or 0),
                int(booking.get("msg_approved_sent", 0) or 0),
                int(booking.get("msg_rejected_sent", 0) or 0),
                int(booking.get("msg_checkedin_sent", 0) or 0),
                int(booking.get("msg_completed_sent", 0) or 0),
                booking.get("source", "customer_portal"),
            ),
        )
        db.commit()
        from utils.helpers import log_action
        log_action("BOOKING CREATED", f"{booking['booking_id']} - {booking['name']}")
    except Exception as e:
        db.rollback()
        from utils.helpers import log_action
        log_action("DB ERROR CREATE BOOKING", f"{booking['booking_id']} - {str(e)}")
        raise
    finally:
        cursor.close()


def update_booking_status(
    booking_id, status, checked_in_at=None, completed_at=None,
    whatsapp_sent=None, actual_visit_date=None, is_rescheduled=None,
    **message_flags
):
    db = get_db()
    cursor = db.cursor()
    try:
        set_clause = (
            "status = %s, "
            "checked_in_at = COALESCE(%s, checked_in_at), "
            "completed_at = COALESCE(%s, completed_at), "
            "whatsapp_sent = COALESCE(%s, whatsapp_sent), "
            "actual_visit_date = COALESCE(%s, actual_visit_date), "
            "is_rescheduled = COALESCE(%s, is_rescheduled)"
        )
        params = [status, checked_in_at, completed_at, whatsapp_sent, actual_visit_date, is_rescheduled]

        for flag, value in message_flags.items():
            if value is not None:
                set_clause += f", {flag} = COALESCE(%s, {flag})"
                params.append(value)

        params.append(booking_id)
        cursor.execute(
            f"UPDATE bookings SET {set_clause} WHERE booking_id = %s",
            params,
        )
        db.commit()
        from utils.helpers import log_action
        log_action("STATUS UPDATED", f"{booking_id} to {status}")
    except Exception as e:
        db.rollback()
        from utils.helpers import log_action
        log_action("DB ERROR UPDATE STATUS", f"{booking_id} - {str(e)}")
        raise
    finally:
        cursor.close()


def update_message_flags(booking_id, **flags):
    db = get_db()
    cursor = db.cursor()
    try:
        set_parts = []
        params = []
        for flag, value in flags.items():
            if value is not None:
                set_parts.append(f"{flag} = %s")
                params.append(int(value))
        if set_parts:
            params.append(booking_id)
            cursor.execute(
                f"UPDATE bookings SET {', '.join(set_parts)} WHERE booking_id = %s",
                params,
            )
            db.commit()
    except Exception as e:
        db.rollback()
        from utils.helpers import log_action
        log_action("DB ERROR UPDATE MSG FLAGS", f"{booking_id} - {str(e)}")
        raise
    finally:
        cursor.close()


def update_whatsapp_sent(booking_id, whatsapp_sent):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            "UPDATE bookings SET whatsapp_sent = %s WHERE booking_id = %s",
            (int(whatsapp_sent), booking_id),
        )
        db.commit()
        from utils.helpers import log_action
        log_action("WHATSAPP SENT", f"{booking_id}")
    except Exception as e:
        db.rollback()
        from utils.helpers import log_action
        log_action("DB ERROR WHATSAPP UPDATE", f"{booking_id} - {str(e)}")
        raise
    finally:
        cursor.close()


def get_latest_booking_id(prefix):
    row = query_dict_one(
        """
        SELECT booking_id
        FROM bookings
        WHERE booking_id LIKE %s
        ORDER BY CAST(SUBSTRING(booking_id FROM %s) AS INTEGER) DESC
        LIMIT 1
        """,
        (f"{prefix}%", len(prefix) + 1),
    )
    return row["booking_id"] if row else None


def count_bookings_for_slot(date):
    placeholders = ", ".join(["%s"] * len(ACTIVE_SLOT_STATUSES))
    row = query_dict_one(
        f"""
        SELECT COUNT(*) AS total
        FROM bookings
        WHERE date = %s
          AND status IN ({placeholders})
          AND COALESCE(source, '') != 'direct_walkin'
        """,
        (date, *ACTIVE_SLOT_STATUSES),
    )
    return row["total"] if row else 0
