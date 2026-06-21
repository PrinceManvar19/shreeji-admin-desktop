"""
cache_sync.py - Syncs Neon -> local SQLite cache.
Uses a direct psycopg2 connection, not Flask g, so it works in background threads.
"""
import os
import threading
import time
import traceback

_sync_lock = threading.Lock()
_last_sync_time = 0
_sync_thread = None
cache_ready = False

SYNC_INTERVAL_SECONDS = 180
SYNC_FAILURE_BACKOFF_CAP_SECONDS = 900


def _get_database_url(app):
    from db_neon import clean_database_url

    return clean_database_url(
        app.config.get("DATABASE_URL") or os.getenv("DATABASE_URL")
    )


def _neon_connect(database_url):
    import psycopg2

    conn = psycopg2.connect(database_url, connect_timeout=5)
    conn.autocommit = True
    return conn


def sync_now(app):
    global _last_sync_time, cache_ready

    with _sync_lock:
        try:
            from db_local import get_local_db
            from psycopg2.extras import RealDictCursor

            database_url = _get_database_url(app)
            if not database_url:
                print("Cache sync: DATABASE_URL not set.", flush=True)
                return False

            neon_conn = _neon_connect(database_url)
            try:
                with neon_conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute("""
                        SELECT booking_id, customer_id, name, phone, vehicle,
                               brand_model, service, date, status, created_at,
                               checked_in_at, completed_at, actual_visit_date,
                               COALESCE(is_rescheduled, 0) AS is_rescheduled,
                               COALESCE(whatsapp_sent, 0) AS whatsapp_sent,
                               COALESCE(msg_approved_sent, 0) AS msg_approved_sent,
                               COALESCE(msg_rejected_sent, 0) AS msg_rejected_sent,
                               COALESCE(msg_checkedin_sent, 0) AS msg_checkedin_sent,
                               COALESCE(msg_completed_sent, 0) AS msg_completed_sent,
                               COALESCE(service_reminder_sent, 0) AS service_reminder_sent,
                               reminder_sent_at, reminder_snooze_until, source
                        FROM bookings
                        ORDER BY created_at DESC
                    """)
                    bookings = [dict(row) for row in cursor.fetchall()]

                    cursor.execute("SELECT id, name, phone, vehicle FROM customers")
                    customers = [dict(row) for row in cursor.fetchall()]

                    cursor.execute("SELECT date, total FROM slots")
                    slots = [dict(row) for row in cursor.fetchall()]
            finally:
                neon_conn.close()

            sqlite_conn = get_local_db()
            try:
                sqlite_conn.execute("DELETE FROM cache_bookings")
                sqlite_conn.executemany("""
                    INSERT OR REPLACE INTO cache_bookings (
                        booking_id, customer_id, name, phone, vehicle,
                        brand_model, service, date, status, created_at,
                        checked_in_at, completed_at, actual_visit_date,
                        is_rescheduled, whatsapp_sent, msg_approved_sent,
                        msg_rejected_sent, msg_checkedin_sent, msg_completed_sent,
                        service_reminder_sent, reminder_sent_at,
                        reminder_snooze_until, source
                    ) VALUES (
                        :booking_id, :customer_id, :name, :phone, :vehicle,
                        :brand_model, :service, :date, :status, :created_at,
                        :checked_in_at, :completed_at, :actual_visit_date,
                        :is_rescheduled, :whatsapp_sent, :msg_approved_sent,
                        :msg_rejected_sent, :msg_checkedin_sent,
                        :msg_completed_sent, :service_reminder_sent,
                        :reminder_sent_at, :reminder_snooze_until, :source
                    )
                """, bookings)

                sqlite_conn.execute("DELETE FROM cache_customers")
                sqlite_conn.executemany(
                    """
                    INSERT OR REPLACE INTO cache_customers (id, name, phone, vehicle)
                    VALUES (:id, :name, :phone, :vehicle)
                    """,
                    customers,
                )

                sqlite_conn.execute("DELETE FROM cache_slots")
                sqlite_conn.executemany(
                    """
                    INSERT OR REPLACE INTO cache_slots (date, total)
                    VALUES (:date, :total)
                    """,
                    slots,
                )
                sqlite_conn.commit()
            finally:
                sqlite_conn.close()

            _last_sync_time = time.time()
            cache_ready = True
            print(
                "Cache sync complete - "
                f"bookings: {len(bookings)}, "
                f"customers: {len(customers)}, "
                f"slots: {len(slots)}",
                flush=True,
            )
            return True

        except Exception as error:
            print(f"Cache sync failed: {error}", flush=True)
            traceback.print_exc()
            return False


def update_booking_in_cache(booking_id, app):
    """Refresh a single booking in the cache after a write to Neon."""
    try:
        from db_local import get_local_db
        from psycopg2.extras import RealDictCursor

        database_url = _get_database_url(app)
        if not database_url:
            return

        neon_conn = _neon_connect(database_url)
        try:
            with neon_conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT booking_id, customer_id, name, phone, vehicle,
                           brand_model, service, date, status, created_at,
                           checked_in_at, completed_at, actual_visit_date,
                           COALESCE(is_rescheduled, 0) AS is_rescheduled,
                           COALESCE(whatsapp_sent, 0) AS whatsapp_sent,
                           COALESCE(msg_approved_sent, 0) AS msg_approved_sent,
                           COALESCE(msg_rejected_sent, 0) AS msg_rejected_sent,
                           COALESCE(msg_checkedin_sent, 0) AS msg_checkedin_sent,
                           COALESCE(msg_completed_sent, 0) AS msg_completed_sent,
                           COALESCE(service_reminder_sent, 0) AS service_reminder_sent,
                           reminder_sent_at, reminder_snooze_until, source
                    FROM bookings
                    WHERE booking_id = %s
                """, (booking_id,))
                row = cursor.fetchone()
        finally:
            neon_conn.close()

        if not row:
            return

        sqlite_conn = get_local_db()
        try:
            sqlite_conn.execute("""
                INSERT OR REPLACE INTO cache_bookings (
                    booking_id, customer_id, name, phone, vehicle,
                    brand_model, service, date, status, created_at,
                    checked_in_at, completed_at, actual_visit_date,
                    is_rescheduled, whatsapp_sent, msg_approved_sent,
                    msg_rejected_sent, msg_checkedin_sent, msg_completed_sent,
                    service_reminder_sent, reminder_sent_at,
                    reminder_snooze_until, source
                ) VALUES (
                    :booking_id, :customer_id, :name, :phone, :vehicle,
                    :brand_model, :service, :date, :status, :created_at,
                    :checked_in_at, :completed_at, :actual_visit_date,
                    :is_rescheduled, :whatsapp_sent, :msg_approved_sent,
                    :msg_rejected_sent, :msg_checkedin_sent,
                    :msg_completed_sent, :service_reminder_sent,
                    :reminder_sent_at, :reminder_snooze_until, :source
                )
            """, dict(row))
            sqlite_conn.commit()
        finally:
            sqlite_conn.close()

        print(f"Cache updated for booking {booking_id}", flush=True)

    except Exception as error:
        print(f"Cache update failed for {booking_id}: {error}", flush=True)
        traceback.print_exc()


def update_slot_in_cache(slot_date, app, old_slot_date=None):
    """Refresh a single slot in the cache after a write to Neon."""
    try:
        from db_local import get_local_db
        from psycopg2.extras import RealDictCursor

        database_url = _get_database_url(app)
        if not database_url:
            return

        neon_conn = _neon_connect(database_url)
        try:
            with neon_conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT date, total FROM slots WHERE date = %s",
                    (slot_date,),
                )
                row = cursor.fetchone()
        finally:
            neon_conn.close()

        sqlite_conn = get_local_db()
        try:
            if old_slot_date and old_slot_date != slot_date:
                sqlite_conn.execute("DELETE FROM cache_slots WHERE date = ?", (old_slot_date,))
            if row:
                sqlite_conn.execute(
                    """
                    INSERT OR REPLACE INTO cache_slots (date, total)
                    VALUES (:date, :total)
                    """,
                    dict(row),
                )
            sqlite_conn.commit()
        finally:
            sqlite_conn.close()

        print(f"Cache updated for slot {slot_date}", flush=True)

    except Exception as error:
        print(f"Cache update failed for slot {slot_date}: {error}", flush=True)
        traceback.print_exc()


def _background_loop(app):
    with app.app_context():
        failure_count = 0
        if sync_now(app):
            failure_count = 0
        else:
            failure_count = 1

        while True:
            if failure_count:
                delay = min(
                    SYNC_INTERVAL_SECONDS * (2 ** (failure_count - 1)),
                    SYNC_FAILURE_BACKOFF_CAP_SECONDS,
                )
                print(
                    f"Cache sync retry delayed for {delay} seconds "
                    f"after {failure_count} failure(s).",
                    flush=True,
                )
            else:
                delay = SYNC_INTERVAL_SECONDS

            time.sleep(delay)
            if sync_now(app):
                failure_count = 0
            else:
                failure_count += 1


def start_background_sync(app):
    global _sync_thread
    if _sync_thread and _sync_thread.is_alive():
        return
    _sync_thread = threading.Thread(
        target=_background_loop,
        args=(app,),
        name="cache-sync",
        daemon=True,
    )
    _sync_thread.start()
