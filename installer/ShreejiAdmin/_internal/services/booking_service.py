import re
from datetime import datetime, timedelta

from db_neon import query_dict_one
from models.audit_log_model import log_audit_action
from models.booking_model import (
    booking_id_exists,
    check_duplicate_booking,
    create_booking,
    get_booking_by_id as fetch_booking_by_id,
    get_bookings_by_customer,
    get_latest_booking_id,
    get_today_bookings as fetch_today_bookings,
    search_bookings,
    update_booking_status,
)
from models.customer_model import get_customer_by_id, get_customer_map
from models.customer_model import get_customer_map_local
from services.slot_service import get_slot_availability
from utils.constants import (
    STATUS_APPROVED,
    STATUS_CHECKED_IN,
    STATUS_COMPLETED,
    STATUS_PENDING,
    STATUS_REJECTED,
)
from utils.helpers import (
    format_date_display,
    format_datetime_display,
    get_status_display,
    is_valid_indian_number_plate,
    log_action,
    normalize_number_plate,
    normalize_phone,
    parse_datetime,
    sort_bookings_newest_first,
)
from utils.validators import is_valid_status_transition

PHONE_PATTERN = re.compile(r"^\d{10}$")


def _normalize_booking_data(name, phone, vehicle, brand_model, service, date):
    normalized_name = (name or "").strip()
    normalized_phone = normalize_phone(phone)
    normalized_vehicle = normalize_number_plate(vehicle)
    normalized_brand_model = (brand_model or "").strip()
    normalized_service = (service or "").strip()
    normalized_date = (date or "").strip()

    return (
        normalized_name,
        normalized_phone,
        normalized_vehicle,
        normalized_brand_model,
        normalized_service,
        normalized_date,
    )


def enrich_booking(booking, customer_map=None):
    customer_map = customer_map or get_customer_map()

    enriched = dict(booking)

    customer = customer_map.get(enriched.get("customer_id", ""), {})

    if not enriched.get("phone"):
        enriched["phone"] = customer.get("phone", "")

    enriched["status_display"] = get_status_display(enriched.get("status"))
    enriched["formatted_date"] = format_date_display(enriched.get("date"))
    enriched["formatted_actual_visit_date"] = format_date_display(
        enriched.get("actual_visit_date")
    )
    enriched["formatted_created_at"] = format_datetime_display(
        enriched.get("created_at")
    )
    enriched["formatted_checked_in_at"] = format_datetime_display(
        enriched.get("checked_in_at")
    )
    enriched["formatted_completed_at"] = format_datetime_display(
        enriched.get("completed_at")
    )
    enriched["slot_label"] = (
        "Walk-in"
        if enriched.get("source") == "direct_walkin"
        else (enriched.get("formatted_date") or enriched.get("date") or "")
    )

    return enriched


def generate_unique_booking_id(prefix):
    # This is still optimistic under concurrent booking requests. A Neon sequence
    # or locked counter table would make ID allocation atomic.
    latest_id = get_latest_booking_id(prefix)

    start_number = (
        1001 if not latest_id else int(latest_id.replace(prefix, "")) + 1
    )

    for number in range(start_number, start_number + 25):
        booking_id = f"{prefix}{number:04d}"

        if not booking_id_exists(booking_id):
            return booking_id

    raise ValueError("Unable to generate a unique booking ID.")


def get_customer_bookings(customer_id):
    customer_map = get_customer_map()

    bookings = [
        enrich_booking(booking, customer_map)
        for booking in get_bookings_by_customer(customer_id)
    ]

    return sort_bookings_newest_first(bookings)


def get_customer_dashboard_data(customer_id):
    bookings = get_customer_bookings(customer_id)

    completed_bookings = [
        booking
        for booking in bookings
        if booking.get("status") == STATUS_COMPLETED
    ]

    latest_completed = (
        sort_bookings_newest_first(completed_bookings)[0]
        if completed_bookings
        else None
    )

    due_for_service = False
    last_service_date = None
    next_service_date = None

    if latest_completed is not None:
        completed_at = parse_datetime(
            latest_completed.get("completed_at")
        ) or parse_datetime(latest_completed.get("date"))

        if completed_at and datetime.now() - completed_at > timedelta(days=90):
            due_for_service = True

        if completed_at:
            last_service_date = completed_at.strftime("%Y-%m-%d")
            next_service_date = (
                completed_at + timedelta(days=90)
            ).strftime("%Y-%m-%d")

    return {
        "bookings": bookings,
        "latest_completed_booking": latest_completed,
        "due_for_service": due_for_service,
        "last_service_date": last_service_date,
        "next_service_date": next_service_date,
    }


def _validate_phone(phone):
    return bool(PHONE_PATTERN.fullmatch(normalize_phone(phone)))


def _validate_booking_input(customer_id, phone, vehicle, service, date):
    normalized_customer_id = (customer_id or "").strip().upper()
    normalized_phone = normalize_phone(phone)
    normalized_vehicle = normalize_number_plate(vehicle)
    normalized_service = (service or "").strip()
    normalized_date = (date or "").strip()

    if not normalized_customer_id:
        return False, "Customer ID is required."

    if not get_customer_by_id(normalized_customer_id):
        return False, "Customer not found."

    if not _validate_phone(normalized_phone):
        return False, "Phone number must be exactly 10 digits."

    if not normalized_vehicle:
        return False, "Vehicle number is required."

    if not is_valid_indian_number_plate(normalized_vehicle):
        return False, "Invalid Indian vehicle number format."

    if not normalized_service:
        return False, "Service is required."

    if not normalized_date:
        return False, "Date is required."

    try:
        datetime.strptime(normalized_date, "%Y-%m-%d")
    except ValueError:
        return False, "Invalid date format."

    return True, ""


def create_booking_for_customer(
    customer_id,
    name,
    phone,
    vehicle,
    brand_model,
    service,
    date,
    performed_by=None,
    source="customer_portal",
    slot_id="date",
):
    normalized_name, normalized_phone, normalized_vehicle, normalized_brand_model, normalized_service, normalized_date = _normalize_booking_data(
        name, phone, vehicle, brand_model, service, date
    )

    normalized_customer_id = (customer_id or "").strip().upper()

    if not normalized_customer_id:
        return False, "Customer ID is required.", None

    duplicate = check_duplicate_booking(
        normalized_phone,
        normalized_vehicle,
        normalized_date,
    )

    if duplicate:
        return (
            False,
            f"Booking already exists for this vehicle ({normalized_vehicle}) on "
            f"{format_date_display(normalized_date)}. "
            f"Existing booking ID: {duplicate['booking_id']}",
            None,
        )

    existing = query_dict_one(
        """
        SELECT COUNT(*) AS count
        FROM bookings
        WHERE customer_id = %s
        AND date = %s
        AND status NOT IN ('rejected', 'completed')
        """,
        (normalized_customer_id, normalized_date),
    )

    if existing and existing["count"] > 0:
        return False, "You already have a booking on this date.", None

    is_valid, message = _validate_booking_input(
        normalized_customer_id,
        normalized_phone,
        normalized_vehicle,
        normalized_service,
        normalized_date,
    )

    if not is_valid:
        log_action(
            "BOOKING VALIDATION FAILED",
            f"{normalized_customer_id} - {message}",
        )
        return False, message, None

    customer = get_customer_by_id(normalized_customer_id)

    resolved_phone = normalized_phone or normalize_phone(
        customer.get("phone", "")
    )

    direct_walkin = slot_id is None
    now_text = datetime.now().strftime("%Y-%m-%d %H:%M")

    booking = {
        "booking_id": generate_unique_booking_id("BOOK"),
        "customer_id": normalized_customer_id,
        "name": normalized_name or customer.get("name", ""),
        "phone": resolved_phone,
        "vehicle": normalized_vehicle,
        "brand_model": normalized_brand_model,
        "service": normalized_service,
        "date": normalized_date,
        "status": STATUS_CHECKED_IN if direct_walkin else STATUS_PENDING,
        "created_at": now_text,
        "checked_in_at": now_text if direct_walkin else None,
        "completed_at": None,
        "actual_visit_date": normalized_date if direct_walkin else None,
        "is_rescheduled": 0,
        "whatsapp_sent": 0,
        "msg_approved_sent": 0,
        "msg_rejected_sent": 0,
        "msg_checkedin_sent": 0,
        "msg_completed_sent": 0,
        "source": source,
    }

    try:
        if not direct_walkin:
            slot = get_slot_availability(booking["date"])

            if not slot:
                return False, "No slots available for selected date.", None

            if slot["available"] <= 0:
                return False, "All slots are booked for this date.", None

        create_booking(booking)

        try:
            log_audit_action(
                booking_id=booking["booking_id"],
                action="booking_created",
                performed_by=performed_by,
                performed_by_id=normalized_customer_id,
                details={
                    "customer_name": booking["name"],
                    "phone": booking["phone"],
                    "vehicle": booking["vehicle"],
                    "service": booking["service"],
                    "date": booking["date"],
                    "source": source,
                },
            )

        except Exception:
            pass

    except Exception as error:
        log_action(
            "BOOKING ERROR",
            f"{booking.get('booking_id', 'unknown')} - {error}",
        )

        return (
            False,
            "Booking could not be saved right now. Please try again.",
            None,
        )

    return True, "", booking

def get_booking_by_id(booking_id):
    booking = fetch_booking_by_id(booking_id)
    if not booking:
        return None
    return enrich_booking(booking)


def get_admin_bookings(filters=None):
    filters = filters or {}

    bookings = search_bookings(
        query=filters.get("query"),
        date=filters.get("date"),
        status=filters.get("status"),
    )

    customer_map = get_customer_map()

    return [
        enrich_booking(booking, customer_map)
        for booking in bookings
    ]


def get_admin_bookings_local(filters=None):
    from models.booking_model import search_bookings_local

    filters = filters or {}
    bookings = search_bookings_local(
        query=filters.get("query"),
        date=filters.get("date"),
        status=filters.get("status"),
    )
    customer_map = get_customer_map_local()
    return [enrich_booking(booking, customer_map) for booking in bookings]


def get_today_bookings(today_date, customer_map=None):
    if customer_map is None:
        customer_map = get_customer_map()

    return [
        enrich_booking(booking, customer_map)
        for booking in fetch_today_bookings(today_date)
    ]


def get_today_bookings_local(today_date):
    from models.booking_model import get_today_bookings_local as fetch_local

    customer_map = get_customer_map_local()
    return [enrich_booking(booking, customer_map) for booking in fetch_local(today_date)]


def get_booking_stats(bookings):
    stats = {
        "total": len(bookings),
        "pending": 0,
        "approved": 0,
        "checked_in": 0,
        "completed": 0,
        "rejected": 0,
    }

    for booking in bookings:
        status = booking.get("status")

        if status in stats:
            stats[status] += 1

    return stats


def get_today_stats(today_date):
    bookings = get_today_bookings(today_date)
    return get_booking_stats(bookings)


def get_today_stats_local(today_date):
    bookings = get_today_bookings_local(today_date)
    return get_booking_stats(bookings)


def approve_booking(booking_id, performed_by=None):
    booking = fetch_booking_by_id(booking_id)

    if not booking:
        return False, "Booking not found.", None

    update_booking_status(
        booking_id,
        STATUS_APPROVED,
        msg_approved_sent=0,
    )

    updated = fetch_booking_by_id(booking_id)

    return True, "Booking approved.", updated


def reject_booking(booking_id, performed_by=None):
    booking = fetch_booking_by_id(booking_id)

    if not booking:
        return False, "Booking not found.", None

    update_booking_status(
        booking_id,
        STATUS_REJECTED,
        msg_rejected_sent=0,
    )

    updated = fetch_booking_by_id(booking_id)

    return True, "Booking rejected.", updated


def checkin_vehicle(booking_id, today_date, performed_by=None):
    booking = fetch_booking_by_id(booking_id)

    if not booking:
        return False, "Booking not found.", None

    update_booking_status(
        booking_id,
        STATUS_CHECKED_IN,
        checked_in_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        actual_visit_date=today_date,
        msg_checkedin_sent=0,
    )

    updated = fetch_booking_by_id(booking_id)

    return True, "Vehicle checked in.", updated


def reschedule_checkin(booking_id, today_date, performed_by=None):
    return checkin_vehicle(booking_id, today_date, performed_by)


def complete_booking_by_id(booking_id, performed_by=None):
    booking = fetch_booking_by_id(booking_id)

    if not booking:
        return False, "Booking not found.", None

    update_booking_status(
        booking_id,
        STATUS_COMPLETED,
        completed_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        msg_completed_sent=0,
    )

    updated = fetch_booking_by_id(booking_id)

    return True, "Vehicle marked completed.", updated


def build_whatsapp_message(booking):
    if not booking:
        return None, {}

    status = booking.get("status", "")
    name = booking.get("name", "")
    booking_id = booking.get("booking_id", "")

    if not name or not booking_id:
        return None, {}

    message = (
        f"Hello {name}, your booking {booking_id} "
        f"status is now: {status.upper()}."
    )

    flags = {}

    if status == STATUS_APPROVED:
        flags["msg_approved_sent"] = 1

    elif status == STATUS_REJECTED:
        flags["msg_rejected_sent"] = 1

    elif status == STATUS_CHECKED_IN:
        flags["msg_checkedin_sent"] = 1

    elif status == STATUS_COMPLETED:
        flags["msg_completed_sent"] = 1

    return message, flags


def create_manual_booking_with_customer(
    customer_id,
    name,
    phone,
    vehicle,
    brand_model,
    service,
    date,
    performed_by=None,
    slot_id=None,
):
    return create_booking_for_customer(
        customer_id,
        name,
        phone,
        vehicle,
        brand_model,
        service,
        date,
        performed_by,
        source="direct_walkin" if slot_id is None else "manual",
        slot_id=slot_id,
    )
