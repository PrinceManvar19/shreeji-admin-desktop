from flask import Blueprint, flash, redirect, render_template, request, session, url_for, jsonify
from models.customer_model import add_vehicle_to_customer, get_customer_by_id, get_customer_by_phone, get_vehicles_by_customer
from services.booking_service import create_booking_for_customer, get_customer_dashboard_data
from services.slot_service import get_next_14_days
from utils.helpers import log_action


customer_bp = Blueprint("customer", __name__)


@customer_bp.route("/api/vehicles/<identifier>")
def api_vehicles(identifier):
    """NEW: Public API - customer vehicles by phone/ID - no login required"""
    vehicles = get_vehicles_by_customer(identifier)
    return jsonify({"vehicles": vehicles})


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
    if "customer_id" not in session or session.get("role") != "customer":
        flash("Please login first", "error")
        return redirect(url_for("auth.login"))

    if request.method == "GET":
        customer = get_customer_by_id(session["customer_id"]) or {
            "id": session["customer_id"],
            "name": session["name"],
            "phone": session.get("phone", ""),
        }
        return render_template(
            "book.html",
            customer=customer,
            date_slots=get_next_14_days(),
        )

    vehicle = request.form.get("vehicle_number", "").strip().upper()
    brand_model = request.form.get("brand_model", "").strip()
    service = request.form.get("service", "").strip()
    date = request.form.get("date", "").strip()
    customer_phone = request.form.get("customer_phone", "").strip() or session.get("phone", "").strip()

    success, message, booking = create_booking_for_customer(
        session["customer_id"],
        session["name"],
        customer_phone,
        vehicle,
        brand_model,
        service,
        date,
        performed_by=session["customer_id"],
    )

    wants_json = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    if not success:
        if wants_json:
            return jsonify({"success": False, "message": message}), 400
        flash(message, "danger")
        return redirect(url_for("customer.dashboard"))

    if wants_json:
        return jsonify({
            "success": True,
            "message": "Booking request sent successfully.",
            "booking_id": booking["booking_id"],
            "status": booking["status"],
        })

    flash(f'Booking request sent successfully. Your Booking ID is {booking["booking_id"]}', "success")
    return redirect(url_for("customer.dashboard"))
