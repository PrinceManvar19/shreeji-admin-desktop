from models.db import get_db
from utils.constants import ACTIVE_SLOT_STATUSES, STATUS_CHECKED_IN


BOOKING_COLUMNS = """
    booking_id, customer_id, name, phone, vehicle, brand_model,
    service, date, status, created_at, checked_in_at, completed_at, whatsapp_sent,
    actual_visit_date, is_rescheduled, msg_approved_sent, msg_rejected_sent,
    msg_checkedin_sent, msg_completed_sent
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
    booking["checked_in"] = booking.get("status") == STATUS_CHECKED_IN
    booking["is_manual"] = not bool(booking.get("customer_id"))
    return booking


def get_all_bookings():
    rows = get_db().execute(f"SELECT {BOOKING_COLUMNS} FROM bookings").fetchall()
    return [row_to_booking(row) for row in rows]


def search_bookings(query=None, date=None, status=None):
    normalized_query = (query or "").strip().lower()
    normalized_date = (date or "").strip() or None
    normalized_status = (status or "").strip().lower() or None
    search_term = f"%{normalized_query}%"

    rows = get_db().execute(
        f"""
        SELECT {BOOKING_COLUMNS}
        FROM bookings
        WHERE (
            ? = '' OR
            LOWER(booking_id) LIKE ? OR
            LOWER(customer_id) LIKE ? OR
            LOWER(phone) LIKE ? OR
            LOWER(vehicle) LIKE ?
        )
        AND (? IS NULL OR status = ?)
        AND (? IS NULL OR date = ?)
        ORDER BY COALESCE(created_at, checked_in_at, date, '') DESC
        LIMIT 50
        """,
        (
            normalized_query,
            search_term,
            search_term,
            search_term,
            search_term,
            normalized_status,
            normalized_status,
            normalized_date,
            normalized_date,
        ),
    ).fetchall()
    return [row_to_booking(row) for row in rows]



def get_today_bookings(today_date):
    rows = get_db().execute(
        f"""
        SELECT {BOOKING_COLUMNS}
        FROM bookings
        WHERE date = ? OR actual_visit_date = ?
        ORDER BY COALESCE(created_at, checked_in_at, date, '') DESC
        LIMIT 50
        """,
        (today_date, today_date),
    ).fetchall()
    return [row_to_booking(row) for row in rows]


def get_booking_by_id(booking_id):

    row = get_db().execute(
        f"SELECT {BOOKING_COLUMNS} FROM bookings WHERE booking_id = ?",
        (booking_id,),
    ).fetchone()
    return row_to_booking(row) if row else None


def booking_id_exists(booking_id):
    row = get_db().execute(
        "SELECT 1 FROM bookings WHERE booking_id = ? LIMIT 1",
        (booking_id,),
    ).fetchone()
    return row is not None


def get_bookings_by_customer(customer_id):
    rows = get_db().execute(
        f"SELECT {BOOKING_COLUMNS} FROM bookings WHERE customer_id = ?",
        (customer_id,),
    ).fetchall()
    return [row_to_booking(row) for row in rows]


def check_duplicate_booking(phone, vehicle, date, exclude_booking_id=None):
    """
    Check for existing bookings with same phone + vehicle + date
    where status is NOT completed or rejected.
    
    Args:
        phone: Normalized phone number (digits only)
        vehicle: Normalized vehicle number (uppercase)
        date: Booking date string
        exclude_booking_id: Optional booking ID to exclude (for updates)
        
    Returns:
        dict or None: The existing booking if found, None otherwise
    """
    normalized_phone = (phone or "").strip()
    normalized_vehicle = (vehicle or "").strip().upper()
    normalized_date = (date or "").strip()
    
    if not normalized_phone or not normalized_vehicle or not normalized_date:
        return None
    
    query = f"""
        SELECT {BOOKING_COLUMNS}
        FROM bookings
        WHERE phone = ?
        AND vehicle = ?
        AND date = ?
        AND status NOT IN ('completed', 'rejected')
    """
    params = [normalized_phone, normalized_vehicle, normalized_date]
    
    if exclude_booking_id:
        query += " AND booking_id != ?"
        params.append(exclude_booking_id)
    
    query += " LIMIT 1"
    
    row = get_db().execute(query, params).fetchone()
    return row_to_booking(row) if row else None


def create_booking(booking):

    try:
        db = get_db()
        db.execute(
            """
            INSERT INTO bookings (
                booking_id, customer_id, name, phone, vehicle, brand_model,
                service, date, status, created_at, checked_in_at, completed_at, whatsapp_sent,
                actual_visit_date, is_rescheduled, msg_approved_sent, msg_rejected_sent,
                msg_checkedin_sent, msg_completed_sent
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )
        from utils.helpers import log_action
        log_action("BOOKING CREATED", f"{booking['booking_id']} - {booking['name']}")
    except Exception as e:
        from utils.helpers import log_action
        log_action("DB ERROR CREATE BOOKING", f"{booking['booking_id']} - {str(e)}")
        raise


def update_booking_status(
    booking_id,
    status,
    checked_in_at=None,
    completed_at=None,
    whatsapp_sent=None,
    actual_visit_date=None,
    is_rescheduled=None,
    **message_flags
):
    try:
        db = get_db()
        set_clause = (
            "status = ?, "
            "checked_in_at = COALESCE(?, checked_in_at), "
            "completed_at = COALESCE(?, completed_at), "
            "whatsapp_sent = COALESCE(?, whatsapp_sent), "
            "actual_visit_date = COALESCE(?, actual_visit_date), "
            "is_rescheduled = COALESCE(?, is_rescheduled)"
        )
        params = [status, checked_in_at, completed_at, whatsapp_sent, actual_visit_date, is_rescheduled]
        
        for flag, value in message_flags.items():
            if value is not None:
                set_clause += f", {flag} = COALESCE(?, {flag})"
                params.append(value)
        
        params.append(booking_id)
        db.execute(
            f"""
            UPDATE bookings
            SET {set_clause}
            WHERE booking_id = ?
            """,
            params
        )
        from utils.helpers import log_action
        log_action("STATUS UPDATED", f"{booking_id} to {status}")
    except Exception as e:
        from utils.helpers import log_action
        log_action("DB ERROR UPDATE STATUS", f"{booking_id} - {str(e)}")
        raise


def update_message_flags(booking_id, **flags):
    """Update specific message flags"""
    try:
        db = get_db()
        set_parts = []
        params = []
        for flag, value in flags.items():
            if value is not None:
                set_parts.append(f"{flag} = ?")
                params.append(int(value))
        params.append(booking_id)
        
        if set_parts:
            db.execute(
                f"""
                UPDATE bookings
                SET {', '.join(set_parts)}
                WHERE booking_id = ?
                """,
                params
            )
    except Exception as e:
        from utils.helpers import log_action
        log_action("DB ERROR UPDATE MSG FLAGS", f"{booking_id} - {str(e)}")
        raise


def update_whatsapp_sent(booking_id, whatsapp_sent):
    try:
        db = get_db()
        db.execute(
            """
            UPDATE bookings
            SET whatsapp_sent = ?
            WHERE booking_id = ?
            """,
            (int(whatsapp_sent), booking_id),
        )
        from utils.helpers import log_action
        log_action("WHATSAPP SENT", f"{booking_id}")
    except Exception as e:
        from utils.helpers import log_action
        log_action("DB ERROR WHATSAPP UPDATE", f"{booking_id} - {str(e)}")
        raise


def get_latest_booking_id(prefix):
    row = get_db().execute(
        """
        SELECT booking_id
        FROM bookings
        WHERE booking_id LIKE ?
        ORDER BY CAST(SUBSTR(booking_id, ?) AS INTEGER) DESC
        LIMIT 1
        """,
        (f"{prefix}%", len(prefix) + 1),
    ).fetchone()
    return row["booking_id"] if row else None


def count_bookings_for_slot(date):
    placeholders = ", ".join("?" for _ in ACTIVE_SLOT_STATUSES)
    row = get_db().execute(
        f"""
        SELECT COUNT(*) AS total
        FROM bookings
        WHERE date = ? AND status IN ({placeholders})
        """,
        (date, *ACTIVE_SLOT_STATUSES),
    ).fetchone()
    return row["total"] if row else 0
