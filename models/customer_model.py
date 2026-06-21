import re
from datetime import datetime

from db_neon import get_neon_db as get_db, query_dict, query_dict_one, execute_query
from utils.helpers import (
    is_valid_indian_number_plate,
    log_action,
    normalize_number_plate,
    normalize_phone,
)


def _generate_customer_id():
    rows = query_dict("SELECT id FROM customers WHERE id LIKE %s", ("CUST%",))
    highest = 1000
    for row in rows:
        match = re.search(r"(\d+)$", row["id"] or "")
        if match:
            highest = max(highest, int(match.group(1)))
    return f"CUST{highest + 1}"


def get_customer_by_id(customer_id):
    row = query_dict_one(
        "SELECT id, name, phone, vehicle, created_at FROM customers WHERE id = %s",
        (customer_id,),
    )
    return dict(row) if row else None


def find_customer(name, phone, vehicle):
    row = query_dict_one(
        """
        SELECT id, name, phone, vehicle, created_at
        FROM customers
        WHERE LOWER(name) = LOWER(%s)
          AND phone = %s
          AND LOWER(vehicle) = LOWER(%s)
        """,
        (name, phone, vehicle),
    )
    return dict(row) if row else None


def get_customer_by_phone(phone):
    normalized_phone = normalize_phone(phone)
    row = query_dict_one(
        "SELECT id, name, phone, vehicle FROM customers WHERE phone = %s",
        (normalized_phone,),
    )
    return dict(row) if row else None


def get_customer_by_phone_or_id(identifier):
    normalized_identifier = (identifier or "").strip()
    normalized_phone = normalize_phone(normalized_identifier)
    normalized_customer_id = normalized_identifier.upper()
    try:
        row = query_dict_one(
            """
            SELECT id, name, phone, vehicle
            FROM customers
            WHERE phone = %s OR id = %s
            LIMIT 1
            """,
            (normalized_phone, normalized_customer_id),
        )
        return dict(row) if row else None
    except Exception as error:
        log_action("LOGIN DB ERROR", str(error))
        return None


def _get_vehicles_for_customer_id(customer_id):
    rows = query_dict(
        """
        SELECT
            cv.id,
            cv.number_plate,
            cv.number_plate AS plate_number,
            cv.brand_model,
            split_part(cv.brand_model, ' ', 1) AS brand,
            CASE
                WHEN POSITION(' ' IN cv.brand_model) > 0
                THEN SUBSTRING(cv.brand_model FROM POSITION(' ' IN cv.brand_model) + 1)
                ELSE ''
            END AS model,
            (
                SELECT MAX(COALESCE(NULLIF(completed_at, ''), NULLIF(actual_visit_date, ''), NULLIF(date, '')))
                FROM bookings b
                WHERE b.customer_id = cv.customer_id
                  AND b.vehicle = cv.number_plate
                  AND b.status = 'completed'
            ) AS last_service_date
        FROM customer_vehicles cv
        WHERE cv.customer_id = %s
        ORDER BY cv.number_plate ASC
        """,
        (customer_id,),
    )
    vehicles = [dict(row) for row in rows]
    if vehicles:
        return vehicles
    customer = get_customer_by_id(customer_id)
    legacy_vehicle = (customer or {}).get("vehicle", "").strip().upper()
    if not legacy_vehicle:
        return []
    log_action(
        "VEHICLE_FALLBACK",
        f"{customer_id} using legacy customers.vehicle {legacy_vehicle}",
    )
    return [{"id": None, "number_plate": legacy_vehicle, "plate_number": legacy_vehicle, "brand_model": "", "brand": "", "model": "", "last_service_date": ""}]


def _set_primary_vehicle_if_missing(customer_id, plate_number):
    customer = get_customer_by_id(customer_id)
    if not customer:
        return
    current_vehicle = (customer.get("vehicle") or "").strip().upper()
    normalized_plate = normalize_number_plate(plate_number)
    if current_vehicle or not normalized_plate:
        return
    execute_query(
        "UPDATE customers SET vehicle = %s WHERE id = %s",
        (normalized_plate, customer_id),
    )


def _upsert_vehicle_record(db, customer_id, plate_number, brand="", model=""):
    normalized_plate = normalize_number_plate(plate_number)
    normalized_brand = (brand or "").strip()
    normalized_model = (model or "").strip()

    if not normalized_plate:
        raise ValueError("Vehicle number is required.")
    if not is_valid_indian_number_plate(normalized_plate):
        raise ValueError("Invalid Indian vehicle number format.")

    cursor = db.cursor()
    from psycopg2.extras import RealDictCursor
    cursor = db.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute(
            """
            SELECT plate_number, customer_id, brand, model
            FROM vehicles WHERE plate_number = %s
            """,
            (normalized_plate,),
        )
        existing_vehicle = cursor.fetchone()

        if existing_vehicle:
            if existing_vehicle["customer_id"] != customer_id:
                raise ValueError("Vehicle number plate is already linked to another customer.")
            next_brand = normalized_brand or (existing_vehicle["brand"] or "")
            next_model = normalized_model or (existing_vehicle["model"] or "")
            cursor.execute(
                "UPDATE vehicles SET brand = %s, model = %s WHERE plate_number = %s",
                (next_brand, next_model, normalized_plate),
            )
            _set_primary_vehicle_if_missing(customer_id, normalized_plate)
            return {"plate_number": normalized_plate, "brand": next_brand, "model": next_model, "created": False}

        cursor.execute(
            "INSERT INTO vehicles (plate_number, customer_id, brand, model) VALUES (%s, %s, %s, %s)",
            (normalized_plate, customer_id, normalized_brand, normalized_model),
        )
        _set_primary_vehicle_if_missing(customer_id, normalized_plate)
        return {"plate_number": normalized_plate, "brand": normalized_brand, "model": normalized_model, "created": True}
    finally:
        cursor.close()


def create_customer(name, phone, vehicle, brand="", model=""):
    normalized_name = (name or "").strip()
    normalized_phone = normalize_phone(phone)
    normalized_vehicle = normalize_number_plate(vehicle)

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

    db = get_db()
    try:
        cursor = db.cursor()
        cursor.execute(
            "INSERT INTO customers (id, name, phone, vehicle) VALUES (%s, %s, %s, %s)",
            (customer["id"], customer["name"], customer["phone"], customer["vehicle"]),
        )
        cursor.close()
        _upsert_vehicle_record(db, customer["id"], normalized_vehicle, brand, model)
        db.commit()
    except Exception as error:
        db.rollback()
        log_action("REGISTRATION DB ERROR", str(error))
        if "unique" in str(error).lower() or "duplicate" in str(error).lower():
            return False, "Phone already registered", None
        return False, "Registration failed. Please try again.", None

    return True, "", customer


def ensure_customer(phone, name, vehicle, brand="", model=""):
    normalized_phone = normalize_phone(phone)
    normalized_name = (name or "").strip()
    normalized_vehicle = normalize_number_plate(vehicle)

    existing = get_customer_by_phone(normalized_phone)
    db = get_db()
    if existing:
        if normalized_vehicle:
            _upsert_vehicle_record(db, existing["id"], normalized_vehicle, brand, model)
            db.commit()
        return get_customer_by_id(existing["id"]) or existing

    customer = {
        "id": _generate_customer_id(),
        "name": normalized_name,
        "phone": normalized_phone,
        "vehicle": normalized_vehicle,
    }
    cursor = db.cursor()
    cursor.execute(
        "INSERT INTO customers (id, name, phone, vehicle) VALUES (%s, %s, %s, %s)",
        (customer["id"], customer["name"], customer["phone"], customer["vehicle"]),
    )
    cursor.close()
    if normalized_vehicle:
        _upsert_vehicle_record(db, customer["id"], normalized_vehicle, brand, model)
    db.commit()
    return customer


def search_customers(query, limit=5):
    normalized_query = (query or "").strip()
    if not normalized_query:
        return []
    search_term = f"%{normalized_query.upper()}%"
    normalized_phone = normalize_phone(normalized_query)
    phone_search_term = f"%{normalized_phone}%" if normalized_phone else None
    rows = query_dict(
        """
        SELECT DISTINCT c.id, c.name, c.phone, c.vehicle
        FROM customers c
        LEFT JOIN vehicles v ON v.customer_id = c.id
        WHERE UPPER(c.id) LIKE %s
           OR UPPER(c.name) LIKE %s
           OR UPPER(c.vehicle) LIKE %s
           OR UPPER(COALESCE(v.plate_number, '')) LIKE %s
           OR (%s IS NOT NULL AND c.phone LIKE %s)
        ORDER BY c.id ASC
        LIMIT %s
        """,
        (search_term, search_term, search_term, search_term, phone_search_term, phone_search_term, limit),
    )
    return [dict(row) for row in rows]


def get_vehicles_by_customer(identifier):
    customer = get_customer_by_phone_or_id(identifier)
    if not customer:
        return []
    return _get_vehicles_for_customer_id(customer["id"])


def get_customer_with_vehicles(identifier):
    customer = get_customer_by_phone_or_id(identifier)
    if not customer:
        return None
    return {"customer": customer, "vehicles": _get_vehicles_for_customer_id(customer["id"])}


def add_vehicle_to_customer(customer_id, plate_number, brand="", model=""):
    normalized_customer_id = (customer_id or "").strip().upper()
    customer = get_customer_by_id(normalized_customer_id)
    if not customer:
        raise ValueError("Customer not found.")
    normalized_plate = normalize_number_plate(plate_number)
    normalized_brand = (brand or "").strip()
    normalized_model = (model or "").strip()
    brand_model = f"{normalized_brand} {normalized_model}".strip()
    add_customer_vehicle(normalized_customer_id, normalized_plate, brand_model)
    return {
        "customer_id": normalized_customer_id,
        "plate_number": normalized_plate,
        "brand": normalized_brand,
        "model": normalized_model,
    }


def _split_brand_model(brand_model):
    parts = (brand_model or "").strip().split(None, 1)
    if not parts:
        return "", ""
    return parts[0], parts[1] if len(parts) > 1 else ""


def _sync_customer_vehicle_to_legacy(db, customer_id, number_plate, brand_model):
    brand, model = _split_brand_model(brand_model)
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO vehicles (plate_number, customer_id, brand, model)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (plate_number) DO UPDATE
            SET customer_id = EXCLUDED.customer_id,
                brand = EXCLUDED.brand,
                model = EXCLUDED.model
            """,
            (number_plate, customer_id, brand, model),
        )
        _set_primary_vehicle_if_missing(customer_id, number_plate)
    finally:
        cursor.close()


def get_customer_vehicle(vehicle_id, customer_id=None):
    normalized_customer_id = (customer_id or "").strip().upper()
    if normalized_customer_id:
        row = query_dict_one(
            """
            SELECT id, customer_id, number_plate, brand_model, created_at
            FROM customer_vehicles
            WHERE id = %s AND customer_id = %s
            """,
            (vehicle_id, normalized_customer_id),
        )
    else:
        row = query_dict_one(
            """
            SELECT id, customer_id, number_plate, brand_model, created_at
            FROM customer_vehicles
            WHERE id = %s
            """,
            (vehicle_id,),
        )
    return dict(row) if row else None


def add_customer_vehicle(customer_id, number_plate, brand_model=""):
    normalized_customer_id = (customer_id or "").strip().upper()
    normalized_plate = normalize_number_plate(number_plate)
    normalized_brand_model = (brand_model or "").strip()

    if not get_customer_by_id(normalized_customer_id):
        raise ValueError("Customer not found.")
    if not normalized_plate:
        raise ValueError("Vehicle number is required.")
    if not is_valid_indian_number_plate(normalized_plate):
        raise ValueError("Invalid Indian vehicle number format.")

    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO customer_vehicles (customer_id, number_plate, brand_model, created_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (number_plate) DO UPDATE
            SET brand_model = EXCLUDED.brand_model
            WHERE customer_vehicles.customer_id = EXCLUDED.customer_id
            RETURNING id, customer_id, number_plate, brand_model, created_at
            """,
            (normalized_customer_id, normalized_plate, normalized_brand_model, datetime.now()),
        )
        row = cursor.fetchone()
        if not row:
            raise ValueError("Vehicle number plate is already linked to another customer.")
        _sync_customer_vehicle_to_legacy(db, normalized_customer_id, normalized_plate, normalized_brand_model)
        db.commit()
        return get_customer_vehicle(row[0], normalized_customer_id)
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def update_customer_vehicle(customer_id, vehicle_id, number_plate, brand_model=""):
    normalized_customer_id = (customer_id or "").strip().upper()
    normalized_plate = normalize_number_plate(number_plate)
    normalized_brand_model = (brand_model or "").strip()

    if not normalized_plate:
        raise ValueError("Vehicle number is required.")
    if not is_valid_indian_number_plate(normalized_plate):
        raise ValueError("Invalid Indian vehicle number format.")

    current = get_customer_vehicle(vehicle_id, normalized_customer_id)
    if not current:
        raise ValueError("Vehicle not found.")

    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            UPDATE customer_vehicles
            SET number_plate = %s, brand_model = %s
            WHERE id = %s AND customer_id = %s
            RETURNING id
            """,
            (normalized_plate, normalized_brand_model, vehicle_id, normalized_customer_id),
        )
        row = cursor.fetchone()
        if not row:
            raise ValueError("Vehicle not found.")
        if current["number_plate"] != normalized_plate:
            cursor.execute("DELETE FROM vehicles WHERE plate_number = %s", (current["number_plate"],))
        _sync_customer_vehicle_to_legacy(db, normalized_customer_id, normalized_plate, normalized_brand_model)
        db.commit()
        return get_customer_vehicle(vehicle_id, normalized_customer_id)
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def delete_customer_vehicle(customer_id, vehicle_id):
    normalized_customer_id = (customer_id or "").strip().upper()
    current = get_customer_vehicle(vehicle_id, normalized_customer_id)
    if not current:
        raise ValueError("Vehicle not found.")

    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            "DELETE FROM customer_vehicles WHERE id = %s AND customer_id = %s",
            (vehicle_id, normalized_customer_id),
        )
        cursor.execute(
            "DELETE FROM vehicles WHERE plate_number = %s AND customer_id = %s",
            (current["number_plate"], normalized_customer_id),
        )
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def ensure_customer_by_phone(phone, name="Guest Customer"):
    normalized_phone = normalize_phone(phone)
    normalized_name = (name or "").strip() or "Guest Customer"
    if len(normalized_phone) != 10:
        raise ValueError("Phone number must be exactly 10 digits.")

    existing = get_customer_by_phone(normalized_phone)
    if existing:
        return existing, False

    customer = {
        "id": _generate_customer_id(),
        "name": normalized_name,
        "phone": normalized_phone,
        "vehicle": "",
    }
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO customers (id, name, phone, vehicle, created_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (customer["id"], customer["name"], customer["phone"], customer["vehicle"], datetime.now()),
        )
        db.commit()
        return customer, True
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()


def get_customer_map():
    rows = query_dict("SELECT id, name, phone, vehicle FROM customers")
    return {row["id"]: dict(row) for row in rows}
