from collections import defaultdict, deque
from datetime import datetime, timedelta

from flask import Blueprint, flash, redirect, render_template, request, session, url_for, jsonify
from models.customer_model import (
    add_customer_vehicle,
    add_vehicle_to_customer,
    delete_customer_vehicle,
    ensure_customer_by_phone,
    get_customer_by_id,
    get_customer_by_phone,
    get_vehicles_by_customer,
    update_customer_vehicle,
)
from services.booking_service import create_booking_for_customer, get_customer_dashboard_data
from services.slot_service import get_next_14_days
from utils.helpers import log_action, normalize_phone


customer_bp = Blueprint("customer", __name__)
_lookup_attempts = defaultdict(deque)


def _client_rate_limited(key, limit=10, window_seconds=60):
    now = datetime.now()
    cutoff = now - timedelta(seconds=window_seconds)
    attempts = _lookup_attempts[key]
    while attempts and attempts[0] < cutoff:
        attempts.popleft()
    if len(attempts) >= limit:
        return True
    attempts.append(now)
    return False


def _session_customer_id():
    return (session.get("customer_id") or "").strip().upper()


def _vehicle_payload(vehicle):
    brand_model = (vehicle.get("brand_model") or "").strip()
    if not brand_model:
        brand_model = f"{vehicle.get('brand', '')} {vehicle.get('model', '')}".strip()
    return {
        "id": vehicle.get("id"),
        "number_plate": vehicle.get("number_plate") or vehicle.get("plate_number"),
        "brand_model": brand_model,
        "last_service_date": vehicle.get("last_service_date") or "",
    }


@customer_bp.route("/api/vehicles/<identifier>")
def api_vehicles(identifier):
    """NEW: Public API - customer vehicles by phone/ID - no login required"""
    vehicles = get_vehicles_by_customer(identifier)
    return jsonify({"vehicles": vehicles})


@customer_bp.route("/api/customer/lookup", methods=["POST"])
def api_customer_lookup():
    rate_key = f"{request.remote_addr or 'unknown'}:{normalize_phone((request.get_json(silent=True) or {}).get('phone') or request.form.get('phone', ''))}"
    if _client_rate_limited(rate_key):
        return jsonify({"success": False, "message": "Too many lookup attempts. Please try again in a minute."}), 429

    data = request.get_json(silent=True) or request.form
    phone = normalize_phone(data.get("phone", ""))
    if len(phone) != 10:
        return jsonify({"success": False, "message": "Phone number must be exactly 10 digits."}), 400

    customer = get_customer_by_phone(phone)
    session["customer_phone"] = phone

    if not customer:
        session.pop("customer_id", None)
        session.pop("name", None)
        session["customer_source"] = "new"
        return jsonify({"found": False})

    session["customer_id"] = customer["id"]
    session["customer_phone"] = phone
    session["name"] = customer["name"]
    session["customer_source"] = "returning"

    vehicles = [_vehicle_payload(vehicle) for vehicle in get_vehicles_by_customer(phone)]
    return jsonify({
        "found": True,
        "name": customer["name"],
        "phone": phone,
        "vehicles": vehicles,
    })


@customer_bp.route("/api/customer/clear", methods=["POST"])
def api_customer_clear():
    for key in ("customer_id", "customer_phone", "name", "customer_source"):
        session.pop(key, None)
    if session.get("role") != "customer":
        session.pop("phone", None)
    return jsonify({"success": True})


@customer_bp.route("/api/customer/vehicle", methods=["POST"])
def api_customer_vehicle_add():
    customer_id = _session_customer_id()
    if not customer_id:
        phone = normalize_phone(session.get("customer_phone") or (request.get_json(silent=True) or {}).get("phone", ""))
        try:
            customer, _created = ensure_customer_by_phone(phone, (request.get_json(silent=True) or {}).get("name", "Guest Customer"))
            customer_id = customer["id"]
            session["customer_id"] = customer_id
            session["customer_phone"] = customer["phone"]
            session["name"] = customer["name"]
            session["customer_source"] = "new" if _created else "returning"
        except ValueError as error:
            return jsonify({"success": False, "message": str(error)}), 400

    data = request.get_json(silent=True) or {}
    try:
        vehicle = add_customer_vehicle(
            customer_id,
            data.get("number_plate") or data.get("plate_number", ""),
            data.get("brand_model", ""),
        )
        return jsonify({"success": True, "vehicle": _vehicle_payload(vehicle)})
    except ValueError as error:
        return jsonify({"success": False, "message": str(error)}), 400
    except Exception as error:
        log_action("CUSTOMER VEHICLE ADD ERROR", str(error))
        return jsonify({"success": False, "message": "Vehicle could not be saved."}), 500


@customer_bp.route("/api/customer/vehicle/<int:vehicle_id>", methods=["PATCH"])
def api_customer_vehicle_edit(vehicle_id):
    customer_id = _session_customer_id()
    if not customer_id:
        return jsonify({"success": False, "message": "Please look up your phone number first."}), 403
    data = request.get_json(silent=True) or {}
    try:
        vehicle = update_customer_vehicle(
            customer_id,
            vehicle_id,
            data.get("number_plate") or data.get("plate_number", ""),
            data.get("brand_model", ""),
        )
        return jsonify({"success": True, "vehicle": _vehicle_payload(vehicle)})
    except ValueError as error:
        return jsonify({"success": False, "message": str(error)}), 400
    except Exception as error:
        log_action("CUSTOMER VEHICLE EDIT ERROR", str(error))
        return jsonify({"success": False, "message": "Vehicle could not be updated."}), 500


@customer_bp.route("/api/customer/vehicle/<int:vehicle_id>", methods=["DELETE"])
def api_customer_vehicle_delete(vehicle_id):
    customer_id = _session_customer_id()
    if not customer_id:
        return jsonify({"success": False, "message": "Please look up your phone number first."}), 403
    try:
        delete_customer_vehicle(customer_id, vehicle_id)
        return jsonify({"success": True})
    except ValueError as error:
        return jsonify({"success": False, "message": str(error)}), 400
    except Exception as error:
        log_action("CUSTOMER VEHICLE DELETE ERROR", str(error))
        return jsonify({"success": False, "message": "Vehicle could not be removed."}), 500


@customer_bp.route("/api/vehicles/add", methods=["POST"])
def api_add_vehicle():
    """NEW: Add new vehicle for logged-in customer"""
    if session.get("role") != "customer":
        return jsonify({"success": False, "message": "Please login as customer first"}), 403

    customer_id = session.get("customer_id")
    if not customer_id:
        phone = session.get("phone")
        customer = get_customer_by_phone(phone)
        if customer:
            customer_id = customer["id"]
    
    if not customer_id:
        return jsonify({"success": False, "message": "Customer not found"}), 400

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "message": "Invalid JSON"}), 400

    plate_number = data.get("plate_number", "").strip().upper()
    brand = data.get("brand", "").strip()
    model = data.get("model", "") or ""

    if not brand:
        return jsonify({"success": False, "message": "Brand required"}), 400

    try:
        vehicle = add_vehicle_to_customer(customer_id, plate_number, brand, model)
        return jsonify({"success": True, "vehicle": vehicle})
    except ValueError as error:
        return jsonify({"success": False, "message": str(error)}), 400
    except Exception as e:
        log_action("ADD VEHICLE ERROR", str(e))
        return jsonify({"success": False, "message": "Database error"}), 500


@customer_bp.route("/dashboard")
def dashboard():
    if "customer_id" not in session or session.get("role") != "customer":
        flash("Please login as customer first", "error")
        return redirect(url_for("auth.login"))

    customer = get_customer_by_id(session["customer_id"]) or {
        "id": session["customer_id"],
        "name": session["name"],
    }
    dashboard_data = get_customer_dashboard_data(session["customer_id"])

    return render_template(
        "dashboard.html",
        customer=customer,
        bookings=dashboard_data["bookings"],
        past_bookings=dashboard_data["bookings"],
        due_for_service=dashboard_data["due_for_service"],
        latest_completed_booking=dashboard_data["latest_completed_booking"],
        last_service_date=dashboard_data["last_service_date"],
        next_service_date=dashboard_data["next_service_date"],
        date_slots=get_next_14_days(),
    )


@customer_bp.route("/book", methods=["GET", "POST"])
def book():
    if request.method == "GET":
        customer = None
        if session.get("customer_id"):
            customer = get_customer_by_id(session["customer_id"])
        if not customer:
            customer = {
                "id": "",
                "name": session.get("name", ""),
                "phone": session.get("customer_phone") or session.get("phone", ""),
            }
        return render_template(
            "book.html",
            customer=customer,
            date_slots=get_next_14_days(),
        )

    customer_name = request.form.get("customer_name", "").strip()
    vehicle = request.form.get("vehicle_number", "").strip().upper()
    brand_model = request.form.get("brand_model", "").strip()
    service = request.form.get("service", "").strip()
    date = request.form.get("date", "").strip()
    customer_phone = request.form.get("customer_phone", "").strip() or session.get("customer_phone", "").strip() or session.get("phone", "").strip()
    source = session.get("customer_source") or ("returning" if session.get("customer_id") else "new")

    if not session.get("customer_id"):
        try:
            customer, created = ensure_customer_by_phone(customer_phone, customer_name)
            session["customer_id"] = customer["id"]
            session["customer_phone"] = customer["phone"]
            session["name"] = customer.get("name") or customer_name
            source = "new" if created else "returning"
            session["customer_source"] = source
        except ValueError as error:
            flash(str(error), "error")
            return redirect(url_for("customer.book"))
    else:
        customer = get_customer_by_id(session["customer_id"]) or {}

    if vehicle:
        try:
            add_customer_vehicle(session["customer_id"], vehicle, brand_model)
        except ValueError as error:
            flash(str(error), "error")
            return redirect(url_for("customer.book"))

    success, message, booking = create_booking_for_customer(
        session["customer_id"],
        customer_name or session.get("name", ""),
        customer_phone,
        vehicle,
        brand_model,
        service,
        date,
        performed_by=session["customer_id"],
        source=source,
    )

    wants_json = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    if not success:
        if wants_json:
            return jsonify({"success": False, "message": message}), 400
        flash(message, "danger")
        return redirect(url_for("customer.book"))

    if wants_json:
        return jsonify({
            "success": True,
            "message": "Booking request sent successfully.",
            "booking_id": booking["booking_id"],
            "status": booking["status"],
        })

    flash(f'Booking request sent successfully. Your Booking ID is {booking["booking_id"]}', "success")
    return redirect(url_for("customer.book"))
