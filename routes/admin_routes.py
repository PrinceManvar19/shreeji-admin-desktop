import csv
import zipfile
from datetime import datetime, timedelta
from io import BytesIO, StringIO
from urllib.parse import quote

from flask import Blueprint, current_app, jsonify, Response, flash, redirect, render_template, request, session, url_for

from db_neon import get_neon_db as get_db, query_dict, query_dict_one
from models.booking_model import count_bookings_for_slot, get_booking_by_id_local, update_message_flags
from models.slot_model import update_slot
from services.booking_service import (
    approve_booking as approve_booking_service,
    normalize_phone,
    reject_booking as reject_booking_service,
    reschedule_checkin,
    build_whatsapp_message,
    checkin_vehicle,
    complete_booking_by_id,
    create_manual_booking_with_customer,
    enrich_booking,
    get_admin_bookings,
    get_admin_bookings_local,
    get_booking_by_id,
    get_booking_stats,
    get_garage_inventory,
    get_today_bookings,
    get_today_bookings_local,
)
from services.service_reminder_service import (
    build_whatsapp_url_for_reminder,
    due_reminder_count,
    due_reminder_count_local,
    list_due_reminders,
    list_due_reminders_local,
    mark_reminder_sent,
    snooze_reminder,
)
from services.slot_service import get_slots_for_admin, get_slots_for_admin_local, set_slot_total
from utils.constants import STATUS_APPROVED, STATUS_CHECKED_IN, STATUS_COMPLETED, STATUS_PENDING, STATUS_REJECTED
from models.customer_model import (
    add_vehicle_to_customer,
    ensure_customer,
    get_customer_by_id,
    get_customer_by_phone,
    get_customer_with_vehicles,
    search_customers,
)
from utils.helpers import format_date_display, format_datetime_display, get_next_days, get_today_date_string, log_action

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def _refresh_cache(booking_id):
    """Refresh a single booking in the local cache after a write to Neon."""
    import threading
    from flask import current_app
    from services.cache_sync import update_booking_in_cache

    app = current_app._get_current_object()
    threading.Thread(
        target=update_booking_in_cache,
        args=(booking_id, app),
        daemon=True,
    ).start()


def _refresh_cache_if_stale():
    """Trigger a background cache sync if cache is older than 90 seconds."""
    import threading
    import time
    from flask import current_app
    import services.cache_sync as cache_sync

    age = time.time() - cache_sync._last_sync_time
    if age > 90:
        app = current_app._get_current_object()
        threading.Thread(
            target=cache_sync.sync_now,
            args=(app,),
            daemon=True,
        ).start()


def _require_admin():
    if session.get("role") != "admin":
        flash("Admin access required", "error")
        return redirect(url_for("auth.login"))
    return None


def _get_current_user_id():
    """Get the current user's ID for audit logging."""
    return session.get("user", {}).get("id") or session.get("admin_id") or "unknown"


def _get_current_user_name():
    """Get the current user's name for audit logging."""
    return session.get("user", {}).get("name") or session.get("name") or "unknown"


@admin_bp.route("")
@admin_bp.route("/")
def admin():
    admin_guard = _require_admin()
    if admin_guard is not None:
        return admin_guard

    today = get_today_date_string()
    bookings = get_admin_bookings({})
    stats = get_booking_stats(bookings)
    today_bookings = get_today_bookings(today)
    today_stats = get_booking_stats(today_bookings)
    vehicles_in_garage = [booking for booking in bookings if booking.get("status") == STATUS_CHECKED_IN]
    late_arrival_bookings = [
        booking
        for booking in bookings
        if booking.get("status") == STATUS_APPROVED and (booking.get("date") or "") < today
    ]

    return render_template(
        "admin.html",
        stats=stats,
        today_stats=today_stats,
        today_bookings=today_bookings,
        late_arrival_bookings=late_arrival_bookings,
        vehicles_in_garage=vehicles_in_garage,
        service_due_count=due_reminder_count_local(),
        booking_data=None,
        checkin_booking_id="",
        today=today,
        today_display=format_date_display(today),
    )


@admin_bp.route("/checkin", methods=["GET", "POST"])
def admin_checkin_page():
    admin_guard = _require_admin()
    if admin_guard is not None:
        return admin_guard

    search_term = (
        request.form.get("q", "")
        if request.method == "POST"
        else request.args.get("q", request.args.get("booking_id", ""))
    ).strip()
    booking_data = None

    if search_term:
        booking_data = get_booking_by_id(search_term.upper())

    today = get_today_date_string()
    today_queue = [
        booking
        for booking in get_today_bookings(today)
        if booking.get("status") == STATUS_APPROVED
    ]
    vehicles_in_garage = get_admin_bookings({"status": STATUS_CHECKED_IN})

    return render_template(
        "checkin.html",
        checkin_booking_id=search_term,
        booking_data=booking_data,
        today_queue=today_queue,
        vehicles_in_garage=vehicles_in_garage,
        today=today,
        today_display=format_date_display(today),
    )


@admin_bp.route("/checkin/verify", methods=["POST"])
def admin_checkin_verify():
    admin_guard = _require_admin()
    if admin_guard is not None:
        return admin_guard
    
    booking_id = request.form.get("booking_id", "")
    if booking_id:
        return redirect(url_for("admin.admin_checkin_page", booking_id=booking_id))
    
    flash("Please provide a booking ID.", "error")
    return redirect(url_for("admin.admin_checkin_page"))


@admin_bp.route("/slots")
def admin_slots():
    admin_guard = _require_admin()
    if admin_guard is not None:
        return admin_guard

    slots_map = get_slots_for_admin()
    return render_template("admin_slots.html", slots=slots_map, today=get_today_date_string())


@admin_bp.route("/bookings")
def admin_bookings():
    admin_guard = _require_admin()
    if admin_guard is not None:
        return admin_guard

    filters = {
        "query": request.args.get("q", "").strip(),
        "date": request.args.get("date", "").strip(),
        "status": request.args.get("status", "").strip(),
    }
    bookings = get_admin_bookings(filters)
    return render_template(
        "admin_bookings.html",
        bookings=bookings,
        filters=filters,
        today=get_today_date_string(),
    )


@admin_bp.route("/garage")
def admin_garage():
    admin_guard = _require_admin()
    if admin_guard is not None:
        return admin_guard

    today = get_today_date_string()
    inventory = get_garage_inventory(today)
    delayed_count = sum(1 for booking in inventory if booking.get("is_delayed"))

    return render_template(
        "admin/garage.html",
        inventory=inventory,
        delayed_count=delayed_count,
        today=today,
        today_display=format_date_display(today),
    )


@admin_bp.route("/service-reminders")
def service_reminders():
    admin_guard = _require_admin()
    if admin_guard is not None:
        return admin_guard
    _refresh_cache_if_stale()

    return render_template(
        "service_reminders.html",
        reminders=list_due_reminders_local(),
    )


@admin_bp.route("/reference")
def admin_reference():
    admin_guard = _require_admin()
    if admin_guard is not None:
        return admin_guard
    return render_template("admin_reference.html")


@admin_bp.route("/service-reminders/<booking_id>/whatsapp")
def service_reminder_whatsapp(booking_id):
    admin_guard = _require_admin()
    if admin_guard is not None:
        return jsonify({"error": "Admin access required"}), 403

    whatsapp_url = build_whatsapp_url_for_reminder(booking_id)
    if not whatsapp_url:
        return jsonify({"error": "WhatsApp reminder could not be opened."}), 400

    mark_reminder_sent(booking_id)
    return jsonify({"whatsapp_url": whatsapp_url})


@admin_bp.route("/service-reminders/<booking_id>/mark-sent", methods=["POST"])
def service_reminder_mark_sent(booking_id):
    admin_guard = _require_admin()
    if admin_guard is not None:
        return admin_guard

    if mark_reminder_sent(booking_id):
        flash("Reminder marked as sent.", "success")
    else:
        flash("Reminder could not be updated.", "error")
    return redirect(url_for("admin.service_reminders"))


@admin_bp.route("/service-reminders/<booking_id>/snooze", methods=["POST"])
def service_reminder_snooze(booking_id):
    admin_guard = _require_admin()
    if admin_guard is not None:
        return admin_guard

    success, snooze_until = snooze_reminder(booking_id, days=7)
    if success:
        flash(f"Reminder snoozed until {snooze_until}.", "success")
    else:
        flash("Reminder could not be snoozed.", "error")
    return redirect(url_for("admin.service_reminders"))


@admin_bp.route("/walkin", methods=["GET", "POST"])
def admin_walkin():
    admin_guard = _require_admin()
    if admin_guard is not None:
        return admin_guard

    today = get_today_date_string()
    if request.method == "POST":
        success, message, booking = _handle_walkin_submission(request.form, today, performed_by=_get_current_user_id())
        if not success:
            flash(message, "error")
        else:
            flash(f'Walk-in vehicle added to garage as {booking["booking_id"]}', "success")
            _refresh_cache(booking["booking_id"])
            fallback = redirect(url_for("admin.admin_walkin"))
            return _redirect_with_whatsapp(booking["booking_id"], booking, fallback)

    return render_template("admin_walkin.html", today=today, slots=get_slots_for_admin())


@admin_bp.route("/export")
def admin_export():
    admin_guard = _require_admin()
    if admin_guard is not None:
        return admin_guard

    return render_template("admin_export.html", today=get_today_date_string())


@admin_bp.route("/set-slots", methods=["POST"])
def set_slots():
    admin_guard = _require_admin()
    if admin_guard is not None:
        return admin_guard

    date = request.form.get("date", "").strip()
    slots_value = request.form.get("slots", "").strip()

    if not date or not slots_value:
        flash("Date and slots are required", "error")
        return redirect(url_for("admin.admin_slots"))

    try:
        total_slots = int(slots_value)
    except ValueError:
        flash("Slots must be a valid number", "error")
        return redirect(url_for("admin.admin_slots"))

    if total_slots < 0:
        flash("Slots cannot be negative", "error")
        return redirect(url_for("admin.admin_slots"))

    if not set_slot_total(date, total_slots):
        flash("Cannot reduce slots below booked count", "error")
        return redirect(url_for("admin.admin_slots"))

    flash("Slots updated successfully", "success")
    return redirect(url_for("admin.admin_slots"))


@admin_bp.route("/slots/<slot_id>/edit", methods=["POST"])
def edit_slot(slot_id):
    admin_guard = _require_admin()
    if admin_guard is not None:
        return admin_guard

    date = request.form.get("date", "").strip()
    time_value = request.form.get("time", "").strip()
    max_bookings_value = (
        request.form.get("max_bookings", "").strip()
        or request.form.get("slots", "").strip()
    )
    status = request.form.get("status", "open").strip().lower()
    booked_count = count_bookings_for_slot(slot_id)

    try:
        max_bookings = int(max_bookings_value)
    except ValueError:
        flash("Max bookings must be a valid number", "error")
        return redirect(url_for("admin.admin_slots"))

    if max_bookings < booked_count:
        flash("Cannot reduce slots below booked count", "error")
        return redirect(url_for("admin.admin_slots"))

    if status == "closed":
        max_bookings = booked_count

    result = update_slot(slot_id, date, time_value, max_bookings, status)
    if not result.get("success"):
        flash(result.get("error", "Slot could not be updated"), "error")
        return redirect(url_for("admin.admin_slots"))

    from services.cache_sync import update_slot_in_cache

    app = current_app._get_current_object()
    update_slot_in_cache(result["slot"]["date"], app, old_slot_date=slot_id)

    flash("Slot updated successfully", "success")
    return redirect(url_for("admin.admin_slots"))


@admin_bp.route("/approve/<booking_id>", methods=["POST"])
def approve_booking(booking_id):
    admin_guard = _require_admin()
    if admin_guard is not None:
        return admin_guard

    success, message, booking = approve_booking_service(
        booking_id,
        performed_by=_get_current_user_id()
    )
    flash(message if not success else "Booking approved", "error" if not success else "success")
    if success:
        _refresh_cache(booking_id)
    fallback = redirect(url_for("admin.admin_bookings"))
    return _redirect_with_whatsapp(booking_id, get_booking_by_id(booking_id) or booking, fallback)


@admin_bp.route("/reject/<booking_id>", methods=["POST"])
def reject_booking(booking_id):
    admin_guard = _require_admin()
    if admin_guard is not None:
        return admin_guard

    success, message, booking = reject_booking_service(
        booking_id,
        performed_by=_get_current_user_id()
    )
    flash(message if not success else "Booking rejected", "error" if not success else "success")
    if success:
        _refresh_cache(booking_id)
    fallback = redirect(url_for("admin.admin_bookings"))
    return _redirect_with_whatsapp(booking_id, get_booking_by_id(booking_id) or booking, fallback)


@admin_bp.route("/checkin/<booking_id>", methods=["POST"])
def admin_checkin_booking(booking_id):
    admin_guard = _require_admin()
    if admin_guard is not None:
        return admin_guard

    success, message, booking = checkin_vehicle(
        booking_id,
        get_today_date_string(),
        performed_by=_get_current_user_id()
    )
    flash(message if not success else "Vehicle checked in successfully", "error" if not success else "success")
    if success:
        _refresh_cache(booking_id)
    fallback = redirect(url_for("admin.admin_checkin_page", booking_id=booking_id))
    return _redirect_with_whatsapp(booking_id, get_booking_by_id(booking_id) or booking, fallback)


@admin_bp.route("/booking/<booking_id>/reschedule-checkin", methods=["POST"])
def admin_reschedule_checkin(booking_id):
    admin_guard = _require_admin()
    if admin_guard is not None:
        if request.is_json:
            return jsonify({"success": False, "error": "Unauthorized"}), 403
        return admin_guard

    today = get_today_date_string()
    success, message, booking = reschedule_checkin(
        booking_id,
        today,
        performed_by=_get_current_user_id(),
    )

    if request.is_json or request.headers.get("Accept", "").find("application/json") >= 0:
        if not success:
            return jsonify({"success": False, "error": message}), 400
        _refresh_cache(booking_id)
        booking_data = get_booking_by_id(booking_id)
        whatsapp_url = _get_whatsapp_url(booking_id, booking_data) if booking_data else None
        return jsonify({
            "success": True,
            "booking_id": booking_id,
            "status": STATUS_CHECKED_IN,
            "actual_visit_date": today,
            "message": "Late arrival checked in",
            "whatsapp_url": whatsapp_url,
        })

    flash(message if not success else "Late arrival checked in successfully", "error" if not success else "success")
    if success:
        _refresh_cache(booking_id)
    fallback = redirect(url_for("admin.admin_checkin_page", booking_id=booking_id))
    return _redirect_with_whatsapp(booking_id, get_booking_by_id(booking_id) or booking, fallback)


@admin_bp.route("/complete/<booking_id>", methods=["POST"])
def complete_booking(booking_id):
    admin_guard = _require_admin()
    if admin_guard is not None:
        return admin_guard

    success, message, booking = complete_booking_by_id(
        booking_id,
        performed_by=session.get("user", {}).get("id", "unknown"),
    )
    flash(message if not success else "Vehicle marked completed", "error" if not success else "success")
    if success:
        _refresh_cache(booking_id)
    fallback = redirect(url_for("admin.admin_checkin_page", booking_id=booking_id))
    return _redirect_with_whatsapp(booking_id, get_booking_by_id(booking_id) or booking, fallback)


@admin_bp.route("/whatsapp/<booking_id>")
def send_booking_whatsapp(booking_id):
    admin_guard = _require_admin()
    if admin_guard is not None:
        return jsonify({"error": "Admin access required"}), 403

    booking = get_booking_by_id(booking_id)
    if not booking:
        return jsonify({"error": "Booking not found"}), 404

    whatsapp_url = _get_whatsapp_url(booking_id, booking)
    if not whatsapp_url:
        return jsonify({"error": "No WhatsApp message is pending for this booking."}), 400
    return jsonify({"whatsapp_url": whatsapp_url})


@admin_bp.route("/find-customer")
def find_customer():
    admin_guard = _require_admin()
    if admin_guard is not None:
        return jsonify({"error": "unauthorized"}), 403

    phone = normalize_phone(request.args.get("phone", "").strip())
    customer = get_customer_by_phone(phone)
    if not customer:
        return jsonify({"found": False})

    return jsonify({
        "found": True,
        "name": customer.get("name", ""),
        "vehicle": customer.get("vehicle", ""),
        "phone": customer.get("phone", ""),
        "customer_id": customer.get("id", ""),
    })


@admin_bp.route("/find-customer-by-id")
def find_customer_by_id():
    admin_guard = _require_admin()
    if admin_guard is not None:
        return jsonify({"error": "unauthorized"}), 403

    customer_id = request.args.get("customer_id", "").strip().upper()
    customer = get_customer_by_id(customer_id)
    if not customer:
        return jsonify({"found": False})

    return jsonify({
        "found": True,
        "name": customer.get("name", ""),
        "phone": customer.get("phone", ""),
        "vehicle": customer.get("vehicle", ""),
        "customer_id": customer.get("id", ""),
    })


@admin_bp.route("/search-customer")
def search_customer():
    admin_guard = _require_admin()
    if admin_guard is not None:
        return jsonify({"error": "unauthorized"}), 403

    query = request.args.get("q", "").strip()
    results = [
        {
            "customer_id": customer.get("id", ""),
            "name": customer.get("name", ""),
            "phone": customer.get("phone", ""),
            "vehicle": customer.get("vehicle", ""),
        }
        for customer in search_customers(query, limit=5)
    ]
    return jsonify(results)


@admin_bp.route("/get-vehicles")
def admin_get_vehicles():
    admin_guard = _require_admin()
    if admin_guard is not None:
        return jsonify({"error": "unauthorized"}), 403

    phone = normalize_phone(request.args.get("phone", "").strip())
    customer_id = request.args.get("customer_id", "").strip().upper()
    identifier = phone or customer_id

    if not identifier:
        return jsonify({"found": False, "customer": None, "vehicles": []}), 400

    lookup = get_customer_with_vehicles(identifier)
    if not lookup:
        return jsonify({"found": False, "customer": None, "vehicles": []})

    customer = lookup["customer"]
    vehicles = [
        {
            "plate": vehicle.get("plate_number", ""),
            "plate_number": vehicle.get("plate_number", ""),
            "brand": vehicle.get("brand", ""),
            "model": vehicle.get("model", ""),
        }
        for vehicle in lookup["vehicles"]
    ]
    return jsonify({
        "found": True,
        "customer": {
            "id": customer.get("id", ""),
            "customer_id": customer.get("id", ""),
            "name": customer.get("name", ""),
            "phone": customer.get("phone", ""),
        },
        "vehicles": vehicles,
    })


@admin_bp.route("/add-vehicle", methods=["POST"])
def admin_add_vehicle():
    admin_guard = _require_admin()
    if admin_guard is not None:
        return jsonify({"success": False, "error": "unauthorized"}), 403

    payload = request.get_json(silent=True) or request.form
    customer_id = payload.get("customer_id", "").strip().upper()
    phone = normalize_phone(payload.get("phone", "").strip())
    plate_number = (payload.get("plate_number") or payload.get("plate") or "").strip().upper()
    brand = payload.get("brand", "").strip()
    model = payload.get("model", "").strip()

    if not plate_number:
        return jsonify({"success": False, "error": "Vehicle number is required."}), 400
    if not brand:
        return jsonify({"success": False, "error": "Brand is required."}), 400

    customer = get_customer_by_id(customer_id) if customer_id else None
    if not customer and phone:
        customer = get_customer_by_phone(phone)
    if not customer:
        return jsonify({"success": False, "error": "Customer not found for this phone number."}), 400

    try:
        vehicle = add_vehicle_to_customer(customer.get("id", ""), plate_number, brand, model)
    except ValueError as error:
        return jsonify({"success": False, "error": str(error)}), 400
    except Exception:
        get_db().rollback()
        return jsonify({"success": False, "error": "Vehicle could not be saved right now."}), 500

    lookup = get_customer_with_vehicles(customer.get("id", ""))
    vehicles = [
        {
            "plate": item.get("plate_number", ""),
            "plate_number": item.get("plate_number", ""),
            "brand": item.get("brand", ""),
            "model": item.get("model", ""),
        }
        for item in (lookup or {}).get("vehicles", [])
    ]

    return jsonify({
        "success": True,
        "customer": {
            "id": customer.get("id", ""),
            "customer_id": customer.get("id", ""),
            "name": customer.get("name", ""),
            "phone": customer.get("phone", ""),
        },
        "vehicle": {
            "plate": vehicle.get("plate_number", ""),
            "plate_number": vehicle.get("plate_number", ""),
            "brand": vehicle.get("brand", ""),
            "model": vehicle.get("model", ""),
        },
        "vehicles": vehicles,
    })


@admin_bp.route("/add-customer", methods=["POST"])
def admin_add_customer():
    admin_guard = _require_admin()
    if admin_guard is not None:
        return jsonify({"success": False, "error": "unauthorized"}), 403

    payload = request.get_json(silent=True) or request.form
    name = payload.get("name", "").strip()
    phone = normalize_phone(payload.get("phone", "").strip())
    vehicle = (payload.get("vehicle") or payload.get("vehicle_number") or "").strip().upper()
    brand = payload.get("brand", "").strip()
    model = payload.get("model", "").strip()

    if not name:
        return jsonify({"success": False, "error": "Customer name is required."}), 400
    if len(phone) != 10:
        return jsonify({"success": False, "error": "Phone number must be exactly 10 digits."}), 400
    if not vehicle:
        return jsonify({"success": False, "error": "Vehicle number is required."}), 400

    try:
        customer = ensure_customer(phone, name, vehicle, brand, model)
    except ValueError as error:
        return jsonify({"success": False, "error": str(error)}), 400
    except Exception as error:
        get_db().rollback()
        log_action("ADD CUSTOMER ERROR", str(error), _get_current_user_id())
        return jsonify({"success": False, "error": "Customer could not be saved right now."}), 500

    lookup = get_customer_with_vehicles(customer.get("id", ""))
    vehicles = [
        {
            "plate": item.get("plate_number", ""),
            "plate_number": item.get("plate_number", ""),
            "brand": item.get("brand", ""),
            "model": item.get("model", ""),
        }
        for item in (lookup or {}).get("vehicles", [])
    ]

    return jsonify({
        "success": True,
        "customer": {
            "id": customer.get("id", ""),
            "customer_id": customer.get("id", ""),
            "name": customer.get("name", ""),
            "phone": customer.get("phone", ""),
        },
        "vehicles": vehicles,
    })


@admin_bp.route("/export-preview")
def export_preview():
    admin_guard = _require_admin()
    if admin_guard is not None:
        return jsonify({"error": "unauthorized"}), 403

    data_type = request.args.get("data_type", "").strip()
    from_date = request.args.get("from_date", "").strip()
    to_date = request.args.get("to_date", "").strip()
    status = request.args.get("status", "").strip()

    if data_type == "bookings":
        count = _count_booking_exports(from_date, to_date, status)
    elif data_type == "customers":
        row = query_dict_one("SELECT COUNT(*) AS total FROM customers")
        count = row["total"] if row else 0
    elif data_type == "garage":
        count = _count_booking_exports(from_date, to_date, garage_only=True)
    elif data_type == "all":
        customer_row = query_dict_one("SELECT COUNT(*) AS total FROM customers")
        count = _count_booking_exports(from_date, to_date, status)
        count += customer_row["total"] if customer_row else 0
    else:
        count = 0

    return jsonify({"count": count})


@admin_bp.route("/export/download")
def export_download():
    admin_guard = _require_admin()
    if admin_guard is not None:
        return admin_guard

    response = _build_export_response(
        request.args.get("data_type", "").strip(),
        request.args.get("from_date", "").strip(),
        request.args.get("to_date", "").strip(),
        request.args.get("status", "").strip(),
    )
    if response is None:
        return "Invalid data_type", 400
    return response


@admin_bp.route("/export-data")
def export_data():
    admin_guard = _require_admin()
    if admin_guard is not None:
        return admin_guard

    return _build_export_response(
        request.args.get("data_type", "all").strip() or "all",
        request.args.get("from_date", "").strip(),
        request.args.get("to_date", "").strip(),
        request.args.get("status", "").strip(),
    )


def _get_whatsapp_url(booking_id, booking):
    if not booking:
        return None

    whatsapp_message, flags = build_whatsapp_message(booking)
    phone = normalize_phone(booking.get("phone", ""))
    if not whatsapp_message or not phone:
        return None

    try:
        if flags:
            update_message_flags(booking_id, **flags)
            get_db().commit()
    except Exception as error:
        get_db().rollback()
        log_action("DB ERROR UPDATE MSG FLAGS", f"{booking_id} - {error}")
        return None

    encoded = quote(whatsapp_message)
    return f"https://wa.me/91{phone}?text={encoded}"


def _redirect_with_whatsapp(booking_id, booking, fallback_response):
    whatsapp_url = _get_whatsapp_url(booking_id, booking)
    if request.headers.get("Accept", "").find("application/json") >= 0:
        return jsonify({"whatsapp_url": whatsapp_url})
    if not whatsapp_url:
        return fallback_response
    flash("WhatsApp message is ready to send.", "success")
    return redirect(whatsapp_url)


def _csv_response(filename, headers, rows):
    return Response(
        _csv_string(headers, rows),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename=\"{filename}\"'},
    )


def _normalize_csv_value(value):
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%d-%m-%Y %H:%M")
    return str(value)


def _format_csv_date(value):
    return _normalize_csv_value(format_date_display(value))


def _format_csv_datetime(value):
    return _normalize_csv_value(format_datetime_display(value))


BOOKING_EXPORT_HEADERS = [
    "booking_id",
    "customer_id",
    "name",
    "phone",
    "vehicle",
    "brand_model",
    "service",
    "date",
    "status",
    "created_at",
    "checked_in_at",
    "completed_at",
]

CUSTOMER_EXPORT_HEADERS = ["id", "name", "phone", "vehicle"]
GARAGE_EXPORT_HEADERS = ["booking_id", "name", "phone", "vehicle", "brand_model", "service", "date", "checked_in_at"]
EXPORT_STATUSES = {STATUS_PENDING, STATUS_APPROVED, STATUS_CHECKED_IN, STATUS_COMPLETED, STATUS_REJECTED}


def _build_last_7_days_data(bookings):
    today = datetime.strptime(get_today_date_string(), "%Y-%m-%d").date()
    days = [today - timedelta(days=offset) for offset in range(6, -1, -1)]
    counts = {day.strftime("%Y-%m-%d"): 0 for day in days}

    for booking in bookings:
        booking_date = booking.get("date")
        if booking_date in counts:
            counts[booking_date] += 1

    return [{"date": format_date_display(date), "count": count} for date, count in counts.items()]


def _booking_filter_clause(from_date="", to_date="", status="", garage_only=False):
    clauses = []
    params = []

    if garage_only:
        clauses.append("status = %s")
        params.append(STATUS_CHECKED_IN)
    elif status in EXPORT_STATUSES:
        clauses.append("status = %s")
        params.append(status)

    if from_date:
        clauses.append("date >= %s")
        params.append(from_date)
    if to_date:
        clauses.append("date <= %s")
        params.append(to_date)

    where_sql = "WHERE " + " AND ".join(clauses) if clauses else ""
    return where_sql, params


def _fetch_booking_export_rows(from_date="", to_date="", status="", garage_only=False):
    where_sql, params = _booking_filter_clause(from_date, to_date, status, garage_only)
    return query_dict(
        f"""
        SELECT booking_id, customer_id, name, phone, vehicle, brand_model, service,
               date, status, created_at, checked_in_at, completed_at
        FROM bookings
        {where_sql}
        ORDER BY date DESC, COALESCE(created_at, checked_in_at, '') DESC
        """,
        params,
    )


def _fetch_customer_export_rows():
    return query_dict("SELECT id, name, phone, vehicle FROM customers ORDER BY id ASC")


def _booking_csv_rows(rows):
    return [
        [
            _normalize_csv_value(row["booking_id"]),
            _normalize_csv_value(row["customer_id"]),
            _normalize_csv_value(row["name"]),
            _normalize_csv_value(row["phone"]),
            _normalize_csv_value(row["vehicle"]),
            _normalize_csv_value(row["brand_model"]),
            _normalize_csv_value(row["service"]),
            _format_csv_date(row["date"]),
            _normalize_csv_value(row["status"]),
            _format_csv_datetime(row["created_at"]),
            _format_csv_datetime(row["checked_in_at"]),
            _format_csv_datetime(row["completed_at"]),
        ]
        for row in rows
    ]


def _garage_csv_rows(rows):
    return [
        [
            _normalize_csv_value(row["booking_id"]),
            _normalize_csv_value(row["name"]),
            _normalize_csv_value(row["phone"]),
            _normalize_csv_value(row["vehicle"]),
            _normalize_csv_value(row["brand_model"]),
            _normalize_csv_value(row["service"]),
            _format_csv_date(row["date"]),
            _format_csv_datetime(row["checked_in_at"]),
        ]
        for row in rows
    ]


def _customer_csv_rows(rows):
    return [
        [
            _normalize_csv_value(row["id"]),
            _normalize_csv_value(row["name"]),
            _normalize_csv_value(row["phone"]),
            _normalize_csv_value(row["vehicle"]),
        ]
        for row in rows
    ]


def _csv_string(headers, rows):
    output = StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)
    writer.writerow(headers)
    writer.writerows(rows)
    return output.getvalue()


def _count_booking_exports(from_date="", to_date="", status="", garage_only=False):
    where_sql, params = _booking_filter_clause(from_date, to_date, status, garage_only)
    row = query_dict_one(f"SELECT COUNT(*) AS total FROM bookings {where_sql}", params)
    return row["total"] if row else 0


def _build_export_response(data_type, from_date="", to_date="", status=""):
    flash("Export successful!", "success")
    if data_type == "bookings":
        rows = _fetch_booking_export_rows(from_date, to_date, status)
        return _csv_response("bookings.csv", BOOKING_EXPORT_HEADERS, _booking_csv_rows(rows))

    if data_type == "customers":
        rows = _fetch_customer_export_rows()
        return _csv_response("customers.csv", CUSTOMER_EXPORT_HEADERS, _customer_csv_rows(rows))

    if data_type == "garage":
        rows = _fetch_booking_export_rows(from_date, to_date, garage_only=True)
        return _csv_response("garage_data.csv", GARAGE_EXPORT_HEADERS, _garage_csv_rows(rows))

    if data_type == "all":
        booking_rows = _fetch_booking_export_rows(from_date, to_date, status)
        customer_rows = _fetch_customer_export_rows()
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            zip_file.writestr(
                "bookings.csv",
                _csv_string(BOOKING_EXPORT_HEADERS, _booking_csv_rows(booking_rows)),
            )
            zip_file.writestr(
                "customers.csv",
                _csv_string(CUSTOMER_EXPORT_HEADERS, _customer_csv_rows(customer_rows)),
            )
        zip_buffer.seek(0)
        return Response(
            zip_buffer.getvalue(),
            mimetype="application/zip",
            headers={"Content-Disposition": 'attachment; filename="admin_data_export.zip"'},
        )

    return None


@admin_bp.route("/api/approve/<booking_id>", methods=["POST"])
def api_approve_booking(booking_id):
    admin_guard = _require_admin()
    if admin_guard is not None:
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    success, message, booking = approve_booking_service(
        booking_id,
        performed_by=_get_current_user_id()
    )
    if not success:
        return jsonify({"success": False, "error": message}), 400

    _refresh_cache(booking_id)
    booking_data = get_booking_by_id(booking_id)
    whatsapp_url = _get_whatsapp_url(booking_id, booking_data) if booking_data else None

    return jsonify({
        "success": True,
        "booking_id": booking_id,
        "status": STATUS_APPROVED,
        "message": "Booking approved",
        "whatsapp_url": whatsapp_url
    })


@admin_bp.route("/api/checkin/<booking_id>", methods=["POST"])
def api_checkin_booking(booking_id):
    admin_guard = _require_admin()
    if admin_guard is not None:
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    success, message, booking = checkin_vehicle(
        booking_id,
        get_today_date_string(),
        performed_by=_get_current_user_id()
    )
    if not success:
        return jsonify({"success": False, "error": message}), 400

    _refresh_cache(booking_id)
    booking_data = get_booking_by_id(booking_id)
    whatsapp_url = _get_whatsapp_url(booking_id, booking_data) if booking_data else None

    return jsonify({
        "success": True,
        "booking_id": booking_id,
        "status": STATUS_CHECKED_IN,
        "message": "Vehicle checked in",
        "whatsapp_url": whatsapp_url
    })


@admin_bp.route("/api/complete/<booking_id>", methods=["POST"])
def api_complete_booking(booking_id):
    admin_guard = _require_admin()
    if admin_guard is not None:
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    success, message, booking = complete_booking_by_id(
        booking_id,
        performed_by=session.get("user", {}).get("id", "unknown"),
    )
    if not success:
        return jsonify({"success": False, "error": message}), 400

    _refresh_cache(booking_id)
    booking_data = get_booking_by_id(booking_id)
    whatsapp_url = _get_whatsapp_url(booking_id, booking_data) if booking_data else None

    return jsonify({
        "success": True,
        "booking_id": booking_id,
        "status": STATUS_COMPLETED,
        "message": "Vehicle marked complete",
        "whatsapp_url": whatsapp_url
    })


def _handle_walkin_submission(form, default_date, performed_by=None):
    customer_id = form.get("customer_id", "").strip().upper()
    name = form.get("name", "").strip()
    phone = form.get("phone", "").strip()
    vehicle = (
        form.get("vehicle_number", "").strip().upper()
        or form.get("vehicle", "").strip().upper()
    )
    vehicle_brand = form.get("vehicle_brand", "").strip()
    vehicle_model = form.get("vehicle_model", "").strip()
    brand_model = form.get("brand_model", "").strip()
    service = form.get("service", "").strip()
    direct_walkin = form.get("no_slot_walkin") == "on"
    slot_id = None if direct_walkin else form.get("slot_id", "").strip()
    date = (default_date if direct_walkin else (slot_id or form.get("date", "").strip())) or default_date

    if not all([name, phone, vehicle, brand_model, service]):
        return False, "Please fill all manual entry fields.", None

    normalized_phone = normalize_phone(phone)
    if len(normalized_phone) != 10:
        return False, "Phone number must be exactly 10 digits.", None

    customer = get_customer_by_id(customer_id) if customer_id else None
    if not customer:
        customer = get_customer_by_phone(normalized_phone)

    if customer:
        customer_id = customer.get("id", "")
        name = customer.get("name", name)
        phone = customer.get("phone", normalized_phone)
    else:
        try:
            customer = ensure_customer(normalized_phone, name, vehicle, vehicle_brand, vehicle_model)
        except Exception as error:
            get_db().rollback()
            log_action("WALKIN CUSTOMER ERROR", str(error))
            return False, "Customer could not be saved right now.", None

        customer_id = customer.get("id", "")
        name = customer.get("name", name)
        phone = customer.get("phone", normalized_phone)

    return create_manual_booking_with_customer(
        customer_id,
        name,
        phone,
        vehicle,
        brand_model,
        service,
        date,
        performed_by=performed_by,
        slot_id=slot_id,
    )
