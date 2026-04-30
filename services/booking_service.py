import re
import sqlite3
from datetime import datetime, timedelta

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
from models.db import get_db
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
    log_action,
    normalize_phone,
    parse_datetime,
    sort_bookings_newest_first,
)
from utils.validators import is_valid_status_transition

PHONE_PATTERN = re.compile(r"^\d{10}$")


def _normalize_booking_data(name, phone, vehicle, brand_model, service, date):
    """
    Normalize all booking input data before validation and storage.
    
    Returns:
        tuple: (normalized_name, normalized_phone, normalized_vehicle, 
                normalized_brand_model, normalized_service, normalized_date)
    """
    normalized_name = (name or "").strip()
    normalized_phone = normalize_phone(phone)
    normalized_vehicle = (vehicle or "").strip().upper()
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
    enriched["formatted_actual_visit_date"] = format_date_display(enriched.get("actual_visit_date"))
    enriched["formatted_created_at"] = format_datetime_display(enriched.get("created_at"))
    enriched["formatted_checked_in_at"] = format_datetime_display(enriched.get("checked_in_at"))
    enriched["formatted_completed_at"] = format_datetime_display(enriched.get("completed_at"))
    return enriched


def generate_unique_booking_id(prefix):
    latest_id = get_latest_booking_id(prefix)
    start_number = 1001 if not latest_id else int(latest_id.replace(prefix, "")) + 1
    for number in range(start_number, start_number + 25):
        booking_id = f"{prefix}{number:04d}"
        if not booking_id_exists(booking_id):
            return booking_id
    raise ValueError("Unable to generate a unique booking ID.")


def get_customer_bookings(customer_id):
    customer_map = get_customer_map()
    bookings = [enrich_booking(booking, customer_map) for booking in get_bookings_by_customer(customer_id)]
    return sort_bookings_newest_first(bookings)


def get_customer_dashboard_data(customer_id):
    bookings = get_customer_bookings(customer_id)
    completed_bookings = [booking for booking in bookings if booking.get("status") == STATUS_COMPLETED]
    latest_completed = sort_bookings_newest_first(completed_bookings)[0] if completed_bookings else None
    due_for_service = False
    last_service_date = None
    next_service_date = None

    if latest_completed is not None:
        completed_at = parse_datetime(latest_completed.get("completed_at")) or parse_datetime(latest_completed.get("date"))
        if completed_at and datetime.now() - completed_at > timedelta(days=90):
            due_for_service = True
        if completed_at:
            last_service_date = completed_at.strftime("%Y-%m-%d")
            next_service_date = (completed_at + timedelta(days=90)).strftime("%Y-%m-%d")

    return {
        "bookings": bookings,
        "latest_completed_booking": latest_completed,
        "due_for_service": due_for_service,
        "last_service_date": last_service_date,
        "next_service_date": next_service_date,
    }


def _validate_phone(phone):
    return bool(PHONE_PATTERN.fullmatch(normalize_phone(phone)))


def _begin_write_transaction():
    get_db().execute("BEGIN IMMEDIATE")


def _validate_booking_input(customer_id, phone, vehicle, service, date):
    if not vehicle:
        return False, "Vehicle number is required."
    if not service:
        return False, "Service is required."
    customer = get_customer_by_id((customer_id or "").strip().upper())
    if not customer:
        return False, "Customer account was not found."
    if not _validate_phone(phone or customer.get("phone", "")):
        return False, "Phone number must be exactly 10 digits."
    slot = get_slot_availability((date or "").strip())
    if not slot:
        return False, "No slots available for selected date."
    if slot["available"] <= 0:
        return False, "All slots are booked for this date."
    return True, ""


def create_booking_for_customer(customer_id, name, phone, vehicle, brand_model, service, date, performed_by=None):
    """
    Create a new booking for a customer with full validation.
    
    Validates:
    - Customer exists
    - Phone is valid (10 digits)
    - Slot is available
    - No duplicate booking (same phone + vehicle + date)
    """
    # Normalize all inputs first
    normalized_name, normalized_phone, normalized_vehicle, normalized_brand_model, normalized_service, normalized_date = _normalize_booking_data(
        name, phone, vehicle, brand_model, service, date
    )
    
    # Validate customer_id
    normalized_customer_id = (customer_id or "").strip().upper()
    if not normalized_customer_id:
        return False, "Customer ID is required.", None
    
    # Check for duplicate booking (phone + vehicle + date)
    duplicate = check_duplicate_booking(normalized_phone, normalized_vehicle, normalized_date)
    if duplicate:
        return False, (
            f"Booking already exists for this vehicle ({normalized_vehicle}) on {format_date_display(normalized_date)}. "
            f"Existing booking ID: {duplicate['booking_id']}"
        ), None
    
    # Check if customer already has a booking on this date
    db = get_db()
    existing = db.execute(
        "SELECT COUNT(*) FROM bookings WHERE customer_id = ? AND date = ? "
        "AND status NOT IN ('rejected', 'completed')",
        (normalized_customer_id, normalized_date),
    ).fetchone()[0]
    if existing > 0:
        return False, "You already have a booking on this date.", None

    # Validate booking input
    is_valid, message = _validate_booking_input(
        normalized_customer_id, normalized_phone, normalized_vehicle, normalized_service, normalized_date
    )
    if not is_valid:
        log_action("BOOKING VALIDATION FAILED", f"{normalized_customer_id} - {message}")
        return False, message, None
    
    customer = get_customer_by_id(normalized_customer_id)
    resolved_phone = normalized_phone or normalize_phone(customer.get("phone", ""))

    booking = {
        "booking_id": generate_unique_booking_id("BOOK"),
        "customer_id": normalized_customer_id,
        "name": normalized_name or customer.get("name", ""),
        "phone": resolved_phone,
        "vehicle": normalized_vehicle,
        "brand_model": normalized_brand_model,
        "service": normalized_service,
        "date": normalized_date,
        "status": STATUS_PENDING,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "checked_in_at": None,
        "completed_at": None,
        "actual_visit_date": None,
        "is_rescheduled": 0,
        "whatsapp_sent": 0,
        "msg_approved_sent": 0,
        "msg_rejected_sent": 0,
        "msg_checkedin_sent": 0,
        "msg_completed_sent": 0,
    }
    
    try:
        _begin_write_transaction()
        slot = get_slot_availability(booking["date"])
        if not slot:
            get_db().rollback()
            return False, "No slots available for selected date.", None
        if slot["available"] <= 0:
            get_db().rollback()
            return False, "All slots are booked for this date.", None
        create_booking(booking)
        get_db().commit()
        
        # Log audit action (wrapped in try/except to never break main flow)
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
                    "source": "customer_portal"
                }
            )
            get_db().commit()
        except Exception:
            pass  # Audit logging should never break main flow
            
    except sqlite3.Error as error:
        get_db().rollback()
        log_action("BOOKING ERROR SQLITE", f"{booking.get('booking_id', 'unknown')} - {error}")
        return False, "Booking could not be saved right now. Please try again.", None
    except Exception as error:
        get_db().rollback()
        log_action("BOOKING ERROR", f"{booking.get('booking_id', 'unknown')} - {error}")
        return False, "Unexpected error occurred. Please try again.", None
    
    return True, "", booking


def create_manual_booking(name, phone, vehicle, brand_model, service, date, customer_id="", performed_by=None):
    """
    Create a manual/walk-in booking with full validation.
    
    Validates:
    - Phone is valid (10 digits)
    - All required fields are present
    - No duplicate booking (same phone + vehicle + date)
    """
    # Normalize all inputs first
    normalized_name, normalized_phone, normalized_vehicle, normalized_brand_model, normalized_service, normalized_date = _normalize_booking_data(
        name, phone, vehicle, brand_model, service, date
    )
    
    if not normalized_phone:
        return False, "Phone number must be exactly 10 digits.", None
    if not all([normalized_name, normalized_vehicle, normalized_brand_model, normalized_service]):
        return False, "Please fill all manual entry fields.", None

    # Check for duplicate booking (phone + vehicle + date)
    duplicate = check_duplicate_booking(normalized_phone, normalized_vehicle, normalized_date)
    if duplicate:
        return False, (
            f"Booking already exists for this vehicle ({normalized_vehicle}) on {format_date_display(normalized_date)}. "
            f"Existing booking ID: {duplicate['booking_id']}"
        ), None

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    booking = {
        "booking_id": generate_unique_booking_id("MANUAL"),
        "customer_id": (customer_id or "").strip().upper(),
        "name": normalized_name,
        "phone": normalized_phone,
        "vehicle": normalized_vehicle,
        "brand_model": normalized_brand_model,
        "service": normalized_service,
        "date": normalized_date,
        "status": STATUS_APPROVED,
        "created_at": timestamp,
        "checked_in_at": None,
        "completed_at": None,
        "actual_visit_date": None,
        "is_rescheduled": 0,
        "whatsapp_sent": 0,
        "msg_approved_sent": 0,
        "msg_rejected_sent": 0,
        "msg_checkedin_sent": 0,
        "msg_completed_sent": 0,
    }
    
    try:
        _begin_write_transaction()
        create_booking(booking)
        get_db().commit()
        
        # Log audit action (wrapped in try/except to never break main flow)
        try:
            log_audit_action(
                booking_id=booking["booking_id"],
                action="booking_created",
                performed_by=performed_by,
                performed_by_id=performed_by or "admin",
                details={
                    "customer_name": booking["name"],
                    "phone": booking["phone"],
                    "vehicle": booking["vehicle"],
                    "service": booking["service"],
                    "date": booking["date"],
                    "source": "walk_in",
                    "customer_id": booking["customer_id"] or None
                }
            )
            get_db().commit()
        except Exception:
            pass  # Audit logging should never break main flow
            
    except sqlite3.Error as error:
        get_db().rollback()
        log_action("WALKIN ERROR SQLITE", f"{booking.get('booking_id', 'unknown')} - {error}")
        return False, "Walk-in entry could not be saved right now. Please try again.", None
    
    return True, "", booking


def create_manual_booking_with_customer(customer_id, name, phone, vehicle, brand_model, service, date, performed_by=None):
    normalized_customer_id = (customer_id or "").strip().upper()
    if normalized_customer_id:
        customer = get_customer_by_id(normalized_customer_id)
        if not customer:
            log_action("WALKIN CUSTOMER NOT FOUND", f"{customer_id}")
            return False, "Customer ID was not found.", None
        name = customer.get("name", name)
        normalized_phone = normalize_phone(customer.get("phone", phone))
        if not normalized_phone:
            return False, "Customer phone invalid", None
        phone = normalized_phone
    else:
        normalized_phone = normalize_phone(phone)
        if not normalized_phone:
            return False, "Phone number must be exactly 10 digits.", None
        phone = normalized_phone

    return create_manual_booking(
        name,
        phone,
        vehicle,
        brand_model,
        service,
        date,
        customer_id=normalized_customer_id,
        performed_by=performed_by,
    )


def get_admin_bookings(filters=None):
    filters = filters or {}
    customer_map = get_customer_map()
    bookings = [
        enrich_booking(booking, customer_map)
        for booking in search_bookings(
            query=filters.get("query"),
            date=filters.get("date"),
            status=filters.get("status"),
        )
    ]
    return sort_bookings_newest_first(bookings)


def get_today_bookings(today_date):
    customer_map = get_customer_map()
    bookings = [
        enrich_booking(booking, customer_map)
        for booking in fetch_today_bookings(today_date)
    ]
    return sort_bookings_newest_first(bookings)


def get_today_stats(today_date):
    bookings = fetch_today_bookings(today_date)
    return {
        "pending": len([b for b in bookings if b.get("status") == STATUS_PENDING]),
        "approved": len([b for b in bookings if b.get("status") == STATUS_APPROVED]),
        "checked_in": len([b for b in bookings if b.get("status") == STATUS_CHECKED_IN]),
        "completed": len([b for b in bookings if b.get("status") == STATUS_COMPLETED]),
    }


def get_booking_by_id(booking_id):
    booking = fetch_booking_by_id(booking_id)
    customer_map = get_customer_map()
    return enrich_booking(booking, customer_map) if booking else None



def get_booking_stats(bookings):
    return {
        "total": len(bookings),
        "pending": len([b for b in bookings if b.get("status") == STATUS_PENDING]),
        "approved": len([b for b in bookings if b.get("status") == STATUS_APPROVED]),
        "completed": len([b for b in bookings if b.get("status") == STATUS_COMPLETED]),
        "rejected": len([b for b in bookings if b.get("status") == STATUS_REJECTED]),
    }


def build_whatsapp_message(booking):
    messages = []
    flags_to_update = {}
    booking_id = booking.get("booking_id", "").strip()
    customer_name = booking.get("name", "").strip() or "Customer"
    vehicle = booking.get("vehicle", "").strip()
    status = booking.get("status")

    if status in [STATUS_APPROVED, STATUS_CHECKED_IN, STATUS_COMPLETED] and not booking["msg_approved_sent"]:
        messages.append(f"Hello {customer_name}, your booking {booking_id} has been approved.")
        flags_to_update["msg_approved_sent"] = 1

    if status in [STATUS_CHECKED_IN, STATUS_COMPLETED] and not booking["msg_checkedin_sent"]:
        if vehicle:
            messages.append(f"Vehicle {vehicle} has been checked in at the garage.")
        else:
            messages.append("Your vehicle has been checked in at the garage.")
        flags_to_update["msg_checkedin_sent"] = 1

    if status == STATUS_COMPLETED and not booking["msg_completed_sent"]:
        messages.append(f"Service for booking {booking_id} is completed. Your vehicle is ready for pickup.")
        flags_to_update["msg_completed_sent"] = 1

    if status == STATUS_REJECTED and not booking["msg_rejected_sent"]:
        messages.append(f"Hello {customer_name}, your booking request {booking_id} was rejected.")
        flags_to_update["msg_rejected_sent"] = 1

    return "\n\n".join(messages), flags_to_update


def approve_booking(booking_id, performed_by=None):
    """
    Approve a pending booking with centralized status validation.
    """
    booking = fetch_booking_by_id(booking_id)
    if not booking:
        return False, "Booking not found.", None
    
    # Use centralized status transition validator
    is_valid, error_message = is_valid_status_transition(booking.get("status"), STATUS_APPROVED)
    if not is_valid:
        return False, error_message, booking

    try:
        _begin_write_transaction()
        # Re-fetch within transaction for consistency
        booking = fetch_booking_by_id(booking_id)
        if not booking:
            get_db().rollback()
            return False, "Booking not found.", None
        
        # Re-validate within transaction
        is_valid, error_message = is_valid_status_transition(booking.get("status"), STATUS_APPROVED)
        if not is_valid:
            get_db().rollback()
            return False, error_message, booking
            
        slot = get_slot_availability(booking["date"])
        if not slot or slot["available"] <= 0:
            get_db().rollback()
            return False, "No slots available for this date.", booking
        
        update_booking_status(booking_id, STATUS_APPROVED)
        get_db().commit()
        
        # Log audit action
        try:
            log_audit_action(
                booking_id=booking_id,
                action="approved",
                performed_by=performed_by,
                performed_by_id=performed_by,
                details={
                    "previous_status": STATUS_PENDING,
                    "new_status": STATUS_APPROVED,
                    "customer_name": booking.get("name"),
                    "vehicle": booking.get("vehicle")
                }
            )
            get_db().commit()
        except Exception:
            pass
            
    except sqlite3.Error:
        get_db().rollback()
        return False, "Booking could not be approved right now. Please try again.", booking
    
    return True, "", fetch_booking_by_id(booking_id)


def reject_booking(booking_id, performed_by=None):
    """
    Reject a pending booking with centralized status validation.
    """
    booking = fetch_booking_by_id(booking_id)
    if not booking:
        return False, "Booking not found.", None
    
    # Use centralized status transition validator
    is_valid, error_message = is_valid_status_transition(booking.get("status"), STATUS_REJECTED)
    if not is_valid:
        return False, error_message, booking

    try:
        _begin_write_transaction()
        # Re-fetch within transaction for consistency
        booking = fetch_booking_by_id(booking_id)
        if not booking:
            get_db().rollback()
            return False, "Booking not found.", None
        
        # Re-validate within transaction
        is_valid, error_message = is_valid_status_transition(booking.get("status"), STATUS_REJECTED)
        if not is_valid:
            get_db().rollback()
            return False, error_message, booking
            
        update_booking_status(booking_id, STATUS_REJECTED)
        get_db().commit()
        
        # Log audit action
        try:
            log_audit_action(
                booking_id=booking_id,
                action="rejected",
                performed_by=performed_by,
                performed_by_id=performed_by,
                details={
                    "previous_status": booking.get("status"),
                    "new_status": STATUS_REJECTED,
                    "customer_name": booking.get("name"),
                    "vehicle": booking.get("vehicle")
                }
            )
            get_db().commit()
        except Exception:
            pass
            
    except sqlite3.Error:
        get_db().rollback()
        return False, "Booking could not be rejected right now. Please try again.", booking
    
    return True, "", fetch_booking_by_id(booking_id)


def checkin_vehicle(booking_id, today, performed_by=None):
    """
    Check in a vehicle with centralized status validation.
    """
    booking = fetch_booking_by_id(booking_id)
    if not booking:
        return False, "Invalid Booking ID.", None
    if booking.get("date") != today:
        return False, "This booking is not scheduled for today.", booking
    
    # Use centralized status transition validator
    is_valid, error_message = is_valid_status_transition(booking.get("status"), STATUS_CHECKED_IN)
    if not is_valid:
        return False, error_message, booking

    checked_in_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        _begin_write_transaction()
        # Re-fetch within transaction for consistency
        booking = fetch_booking_by_id(booking_id)
        if not booking:
            get_db().rollback()
            return False, "Invalid Booking ID.", None
        if booking.get("date") != today:
            get_db().rollback()
            return False, "This booking is not scheduled for today.", booking
        
        # Re-validate within transaction
        is_valid, error_message = is_valid_status_transition(booking.get("status"), STATUS_CHECKED_IN)
        if not is_valid:
            get_db().rollback()
            return False, error_message, booking
            
        update_booking_status(booking_id, STATUS_CHECKED_IN, checked_in_at=checked_in_at)
        get_db().commit()
        
        # Log audit action
        try:
            log_audit_action(
                booking_id=booking_id,
                action="checked_in",
                performed_by=performed_by,
                performed_by_id=performed_by,
                details={
                    "previous_status": STATUS_APPROVED,
                    "new_status": STATUS_CHECKED_IN,
                    "checked_in_at": checked_in_at,
                    "customer_name": booking.get("name"),
                    "vehicle": booking.get("vehicle")
                }
            )
            get_db().commit()
        except Exception:
            pass
            
        log_action("CHECK-IN", booking_id, performed_by)
    except sqlite3.Error:
        get_db().rollback()
        return False, "Vehicle could not be checked-in right now. Please try again.", booking
    
    return True, "", fetch_booking_by_id(booking_id)


def reschedule_checkin(booking_id, actual_visit_date, performed_by=None):
    """
    Check in an approved booking when the customer arrives on a different date.
    Keeps the original booking date and stores the real visit date separately.
    """
    today = (actual_visit_date or "").strip()
    booking = fetch_booking_by_id(booking_id)
    if not booking:
        return False, "Invalid Booking ID.", None
    if booking.get("date") == today:
        return False, "Use normal check-in for bookings scheduled today.", booking

    is_valid, error_message = is_valid_status_transition(booking.get("status"), STATUS_CHECKED_IN)
    if not is_valid:
        return False, error_message, booking

    checked_in_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        _begin_write_transaction()
        booking = fetch_booking_by_id(booking_id)
        if not booking:
            get_db().rollback()
            return False, "Invalid Booking ID.", None
        if booking.get("date") == today:
            get_db().rollback()
            return False, "Use normal check-in for bookings scheduled today.", booking

        is_valid, error_message = is_valid_status_transition(booking.get("status"), STATUS_CHECKED_IN)
        if not is_valid:
            get_db().rollback()
            return False, error_message, booking

        update_booking_status(
            booking_id,
            STATUS_CHECKED_IN,
            checked_in_at=checked_in_at,
            actual_visit_date=today,
            is_rescheduled=1,
        )
        get_db().commit()

        try:
            log_audit_action(
                booking_id=booking_id,
                action="reschedule_checkin",
                performed_by=performed_by,
                performed_by_id=performed_by,
                details={
                    "previous_status": STATUS_APPROVED,
                    "new_status": STATUS_CHECKED_IN,
                    "original_booking_date": booking.get("date"),
                    "actual_visit_date": today,
                    "checked_in_at": checked_in_at,
                    "customer_name": booking.get("name"),
                    "vehicle": booking.get("vehicle"),
                },
            )
            get_db().commit()
        except Exception:
            pass

        log_action("RESCHEDULE CHECK-IN", f"{booking_id} on {today}", performed_by)
    except sqlite3.Error:
        get_db().rollback()
        return False, "Late arrival could not be checked in right now. Please try again.", booking

    return True, "", fetch_booking_by_id(booking_id)


def complete_booking_by_id(booking_id, performed_by=None):
    """
    Mark a checked-in vehicle as complete with centralized status validation.
    """
    booking = fetch_booking_by_id(booking_id)
    if not booking:
        return False, "Booking not found.", None
    
    # Use centralized status transition validator
    is_valid, error_message = is_valid_status_transition(booking.get("status"), STATUS_COMPLETED)
    if not is_valid:
        return False, error_message, booking

    completed_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        _begin_write_transaction()
        # Re-fetch within transaction for consistency
        booking = fetch_booking_by_id(booking_id)
        if not booking:
            get_db().rollback()
            return False, "Booking not found.", None
        
        # Re-validate within transaction
        is_valid, error_message = is_valid_status_transition(booking.get("status"), STATUS_COMPLETED)
        if not is_valid:
            get_db().rollback()
            return False, error_message, booking
            
        update_booking_status(booking_id, STATUS_COMPLETED, completed_at=completed_at)
        get_db().commit()
        
        # Log audit action
        try:
            log_audit_action(
                booking_id=booking_id,
                action="completed",
                performed_by=performed_by,
                performed_by_id=performed_by,
                details={
                    "previous_status": STATUS_CHECKED_IN,
                    "new_status": STATUS_COMPLETED,
                    "completed_at": completed_at,
                    "customer_name": booking.get("name"),
                    "vehicle": booking.get("vehicle")
                }
            )
            get_db().commit()
        except Exception:
            pass
            
        log_action("COMPLETED", booking_id, performed_by)
    except sqlite3.Error:
        get_db().rollback()
        return False, "Vehicle could not be completed right now. Please try again.", booking
    
    return True, "", fetch_booking_by_id(booking_id)
