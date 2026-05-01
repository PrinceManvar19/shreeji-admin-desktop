import re
import sqlite3

from models.db import get_db
from utils.helpers import log_action, normalize_phone


def _generate_customer_id():
    rows = get_db().execute("SELECT id FROM customers WHERE id LIKE 'CUST%'").fetchall()
    highest = 1000
    for row in rows:
        match = re.search(r"(\d+)$", row["id"] or "")
        if match:
            highest = max(highest, int(match.group(1)))
    return f"CUST{highest + 1}"


def get_customer_by_id(customer_id):
    row = get_db().execute(
        "SELECT id, name, phone, vehicle FROM customers WHERE id = ?",
        (customer_id,),
    ).fetchone()
    return dict(row) if row else None


def find_customer(name, phone, vehicle):
    row = get_db().execute(
        """
        SELECT id, name, phone, vehicle
        FROM customers
        WHERE LOWER(name) = LOWER(?)
          AND phone = ?
          AND LOWER(vehicle) = LOWER(?)
        """,
        (name, phone, vehicle),
    ).fetchone()
    return dict(row) if row else None


def get_customer_by_phone(phone):
    normalized_phone = normalize_phone(phone)
    row = get_db().execute(
        "SELECT id, name, phone, vehicle FROM customers WHERE phone = ?",
        (normalized_phone,),
    ).fetchone()
    return dict(row) if row else None


def get_customer_by_phone_or_id(identifier):
    normalized_identifier = (identifier or "").strip()
    normalized_phone = normalize_phone(normalized_identifier)
    normalized_customer_id = normalized_identifier.upper()

    try:
        row = get_db().execute(
            """
            SELECT id, name, phone, vehicle
            FROM customers
            WHERE phone = ? OR id = ?
            LIMIT 1
            """,
            (normalized_phone, normalized_customer_id),
        ).fetchone()
        return dict(row) if row else None
    except Exception as error:
        log_action("LOGIN DB ERROR", str(error))
        return None


def _get_vehicles_for_customer_id(customer_id):
    rows = get_db().execute(
        """
        SELECT plate_number, brand, model
        FROM vehicles
        WHERE customer_id = ?
        ORDER BY plate_number ASC
        """,
        (customer_id,),
    ).fetchall()
    vehicles = [dict(row) for row in rows]

    if vehicles:
        return vehicles

    customer = get_customer_by_id(customer_id)
    legacy_vehicle = (customer or {}).get("vehicle", "").strip().upper()
    if not legacy_vehicle:
        return []

    return [{"plate_number": legacy_vehicle, "brand": "", "model": ""}]


def _set_primary_vehicle_if_missing(customer_id, plate_number):
    customer = get_customer_by_id(customer_id)
    if not customer:
        return

    current_vehicle = (customer.get("vehicle") or "").strip().upper()
    normalized_plate = (plate_number or "").strip().upper()
    if current_vehicle or not normalized_plate:
        return

    get_db().execute(
        "UPDATE customers SET vehicle = ? WHERE id = ?",
        (normalized_plate, customer_id),
    )


def _upsert_vehicle_record(db, customer_id, plate_number, brand="", model=""):
    normalized_plate = (plate_number or "").strip().upper()
    normalized_brand = (brand or "").strip()
    normalized_model = (model or "").strip()

    if not normalized_plate:
        raise ValueError("Vehicle number is required.")
    if not re.fullmatch(r"^[A-Z0-9\s-]{4,15}$", normalized_plate):
        raise ValueError("Invalid vehicle number format.")

    existing_vehicle = db.execute(
        """
        SELECT plate_number, customer_id, brand, model
        FROM vehicles
        WHERE plate_number = ?
        """,
        (normalized_plate,),
    ).fetchone()

    if existing_vehicle:
        if existing_vehicle["customer_id"] != customer_id:
            raise ValueError("Vehicle number plate is already linked to another customer.")

        next_brand = normalized_brand or (existing_vehicle["brand"] or "")
        next_model = normalized_model or (existing_vehicle["model"] or "")
        db.execute(
            """
            UPDATE vehicles
            SET brand = ?, model = ?
            WHERE plate_number = ?
            """,
            (next_brand, next_model, normalized_plate),
        )
        _set_primary_vehicle_if_missing(customer_id, normalized_plate)
        return {
            "plate_number": normalized_plate,
            "brand": next_brand,
            "model": next_model,
            "created": False,
        }

    db.execute(
        """
        INSERT INTO vehicles (plate_number, customer_id, brand, model)
        VALUES (?, ?, ?, ?)
        """,
        (normalized_plate, customer_id, normalized_brand, normalized_model),
    )
    _set_primary_vehicle_if_missing(customer_id, normalized_plate)
    return {
        "plate_number": normalized_plate,
        "brand": normalized_brand,
        "model": normalized_model,
        "created": True,
    }


def create_customer(name, phone, vehicle, brand="", model=""):
    normalized_name = (name or "").strip()
    normalized_phone = normalize_phone(phone)
    normalized_vehicle = (vehicle or "").strip().upper()

    if not all([normalized_name, normalized_phone, normalized_vehicle]):
        return False, "All fields are required.", None
    if len(normalized_phone) != 10:
        return False, "Phone number must be exactly 10 digits.", None

    try:
        existing = get_customer_by_phone(normalized_phone)
    except Exception as error:
        log_action("REGISTRATION DUPLICATE CHECK ERROR", str(error))
        return False, "Registration failed. Please try again.", None

    if existing:
        return False, "Phone already registered", None

    customer = {
        "id": _generate_customer_id(),
        "name": normalized_name,
        "phone": normalized_phone,
        "vehicle": normalized_vehicle,
    }

    try:
        get_db().execute(
            """
            INSERT INTO customers (id, name, phone, vehicle)
            VALUES (?, ?, ?, ?)
            """,
            (customer["id"], customer["name"], customer["phone"], customer["vehicle"]),
        )
        _upsert_vehicle_record(get_db(), customer["id"], normalized_vehicle, brand, model)
        get_db().commit()
    except sqlite3.IntegrityError:
        get_db().rollback()
        log_action("REGISTRATION DB ERROR", "duplicate phone")
        return False, "Phone already registered", None
    except Exception as error:
        get_db().rollback()
        log_action("REGISTRATION DB ERROR", str(error))
        return False, "Registration failed. Please try again.", None

    return True, "", customer


def ensure_customer(phone, name, vehicle, brand="", model=""):
    normalized_phone = normalize_phone(phone)
    normalized_name = (name or "").strip()
    normalized_vehicle = (vehicle or "").strip().upper()

    existing = get_customer_by_phone(normalized_phone)
    if existing:
        if normalized_vehicle:
            _upsert_vehicle_record(get_db(), existing["id"], normalized_vehicle, brand, model)
            get_db().commit()
        return get_customer_by_id(existing["id"]) or existing

    customer = {
        "id": _generate_customer_id(),
        "name": normalized_name,
        "phone": normalized_phone,
        "vehicle": normalized_vehicle,
    }
    get_db().execute(
        """
        INSERT INTO customers (id, name, phone, vehicle)
        VALUES (?, ?, ?, ?)
        """,
        (customer["id"], customer["name"], customer["phone"], customer["vehicle"]),
    )
    if normalized_vehicle:
        _upsert_vehicle_record(get_db(), customer["id"], normalized_vehicle, brand, model)
    get_db().commit()
    return customer


def search_customers(query, limit=5):
    normalized_query = (query or "").strip()
    if not normalized_query:
        return []

    search_term = f"%{normalized_query.upper()}%"
    normalized_phone = normalize_phone(normalized_query)
    phone_search_term = f"%{normalized_phone}%" if normalized_phone else None
    rows = get_db().execute(
        """
        SELECT DISTINCT c.id, c.name, c.phone, c.vehicle
        FROM customers c
        LEFT JOIN vehicles v ON v.customer_id = c.id
        WHERE UPPER(c.id) LIKE ?
           OR UPPER(c.name) LIKE ?
           OR UPPER(c.vehicle) LIKE ?
           OR UPPER(COALESCE(v.plate_number, '')) LIKE ?
           OR (? IS NOT NULL AND c.phone LIKE ?)
        ORDER BY c.id ASC
        LIMIT ?
        """,
        (search_term, search_term, search_term, search_term, phone_search_term, phone_search_term, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def get_vehicles_by_customer(identifier):
    """Get customer vehicles by phone or customer_id."""
    customer = get_customer_by_phone_or_id(identifier)
    if not customer:
        return []

    return _get_vehicles_for_customer_id(customer["id"])


def get_customer_with_vehicles(identifier):
    customer = get_customer_by_phone_or_id(identifier)
    if not customer:
        return None

    return {
        "customer": customer,
        "vehicles": _get_vehicles_for_customer_id(customer["id"]),
    }


def add_vehicle_to_customer(customer_id, plate_number, brand="", model=""):
    normalized_customer_id = (customer_id or "").strip().upper()
    customer = get_customer_by_id(normalized_customer_id)
    if not customer:
        raise ValueError("Customer not found.")

    vehicle = _upsert_vehicle_record(get_db(), normalized_customer_id, plate_number, brand, model)
    get_db().commit()
    return vehicle


def get_customer_map():
    rows = get_db().execute("SELECT id, name, phone, vehicle FROM customers").fetchall()
    return {row["id"]: dict(row) for row in rows}
