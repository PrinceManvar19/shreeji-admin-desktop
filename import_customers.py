import argparse
import re
from datetime import datetime
from pathlib import Path

from app import app
from db_neon import get_neon_db as get_db
from psycopg2.extras import execute_values
from utils.helpers import normalize_number_plate, normalize_phone


DEFAULT_EXCEL_PATH = Path("Customer LIst") / "Customer list all.xlsx"


def _load_rows(path):
    try:
        from openpyxl import load_workbook
    except ImportError as error:
        raise SystemExit("openpyxl is required. Install it with: pip install openpyxl") from error

    workbook = load_workbook(path, read_only=True, data_only=True)
    sheet = workbook.active
    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        return []

    headers = [str(value or "").strip().lower() for value in rows[0]]
    return [
        {
            headers[index] if index < len(headers) and headers[index] else f"column_{index + 1}": value
            for index, value in enumerate(row)
        }
        for row in rows[1:]
    ]


def _pick(row, candidates):
    normalized = {
        re.sub(r"[^a-z0-9]", "", key.lower()): value
        for key, value in row.items()
    }
    for candidate in candidates:
        key = re.sub(r"[^a-z0-9]", "", candidate.lower())
        value = normalized.get(key)
        if value is not None and str(value).strip():
            if isinstance(value, float) and value == int(value):
                return str(int(value))
            return str(value).strip()
    return ""


def _next_customer_id_start(cursor):
    cursor.execute("SELECT id FROM customers WHERE id LIKE 'CUST%'")
    highest = 1000
    for row in cursor.fetchall():
        match = re.search(r"(\d+)$", row[0] or "")
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def _load_existing_customer_map(cursor):
    cursor.execute("SELECT id, phone FROM customers WHERE phone IS NOT NULL AND phone <> ''")
    return {row[1]: row[0] for row in cursor.fetchall()}


def _load_existing_vehicle_plates(cursor):
    cursor.execute("SELECT number_plate FROM customer_vehicles")
    return {row[0] for row in cursor.fetchall()}


def _ensure_tables(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            phone TEXT,
            vehicle TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_customers_phone_unique
        ON customers(phone)
        WHERE phone IS NOT NULL AND phone <> ''
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS customer_vehicles (
            id SERIAL PRIMARY KEY,
            customer_id TEXT NOT NULL,
            number_plate TEXT NOT NULL,
            brand_model TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE,
            UNIQUE (number_plate)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS vehicles (
            plate_number TEXT PRIMARY KEY,
            customer_id TEXT NOT NULL,
            brand TEXT DEFAULT '',
            model TEXT DEFAULT '',
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        )
    """)


def import_customers(path, dry_run=False):
    rows = _load_rows(path)
    db = get_db()
    cursor = db.cursor()
    customers_seen = set()
    vehicles_seen = set()
    customer_rows = []
    customer_vehicle_rows = []
    legacy_vehicle_rows = []
    skipped = 0

    try:
        id_counter = None
        if not dry_run:
            _ensure_tables(cursor)
            id_counter = _next_customer_id_start(cursor)
            phone_to_customer_id = _load_existing_customer_map(cursor)
            existing_vehicle_plates = _load_existing_vehicle_plates(cursor)
        else:
            phone_to_customer_id = {}
            existing_vehicle_plates = set()

        for row in rows:
            phone = normalize_phone(_pick(row, ("c_phone", "cphone", "phone", "mobile", "mobile no", "contact", "contact no", "phone number")))
            plate = normalize_number_plate(_pick(row, ("vehi_num", "vehinum", "number plate", "vehicle number", "vehicle no", "registration number", "reg no", "plate")))
            name = _pick(row, ("c_name", "cname", "name", "customer name", "owner name")) or "Guest Customer"
            brand_model = _pick(row, ("vehi_brand", "vehibrand", "brand model", "brand/model", "vehi_name", "vehiname", "vehicle model", "model", "bike model", "vehicle"))

            if len(phone) != 10 or not plate:
                skipped += 1
                continue

            if dry_run:
                customers_seen.add(phone)
                vehicles_seen.add(plate)
                continue

            existing_customer_id = phone_to_customer_id.get(phone)
            if existing_customer_id:
                customer_id = existing_customer_id
            else:
                customer_id = f"CUST{id_counter}"
                id_counter += 1
                phone_to_customer_id[phone] = customer_id
                customer_rows.append((customer_id, name, phone, plate, datetime.now()))

            customers_seen.add(customer_id)

            if plate not in existing_vehicle_plates:
                existing_vehicle_plates.add(plate)
                vehicles_seen.add(plate)
                customer_vehicle_rows.append((customer_id, plate, brand_model, datetime.now()))

            brand, model = (brand_model.split(None, 1) + [""])[:2] if brand_model else ("", "")
            legacy_vehicle_rows.append((plate, customer_id, brand, model))

        if not dry_run and customer_rows:
            execute_values(
                cursor,
                """
                INSERT INTO customers (id, name, phone, vehicle, created_at)
                VALUES %s
                ON CONFLICT DO NOTHING
                """,
                customer_rows,
                page_size=1000,
            )

        if not dry_run and customer_vehicle_rows:
            execute_values(
                cursor,
                """
                INSERT INTO customer_vehicles (customer_id, number_plate, brand_model, created_at)
                VALUES %s
                ON CONFLICT DO NOTHING
                """,
                customer_vehicle_rows,
                page_size=1000,
            )

        if not dry_run and legacy_vehicle_rows:
            execute_values(
                cursor,
                """
                INSERT INTO vehicles (plate_number, customer_id, brand, model)
                VALUES %s
                ON CONFLICT DO NOTHING
                """,
                legacy_vehicle_rows,
                page_size=1000,
            )

        if not dry_run:
            db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()

    prefix = "Dry run - " if dry_run else ""
    print(f"{prefix}Customers imported/found: {len(customers_seen)}")
    print(f"{prefix}Vehicles imported: {len(vehicles_seen)}")
    print(f"Rows skipped: {skipped}")


def main():
    parser = argparse.ArgumentParser(description="Import customer and vehicle rows from Excel.")
    parser.add_argument("path", nargs="?", default=str(DEFAULT_EXCEL_PATH), help="Path to .xlsx file")
    parser.add_argument("--dry-run", action="store_true", help="Parse and report counts without writing rows")
    args = parser.parse_args()
    path = Path(args.path)
    if not path.exists():
        raise SystemExit(f"Excel file not found: {path}")

    with app.app_context():
        import_customers(path, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
