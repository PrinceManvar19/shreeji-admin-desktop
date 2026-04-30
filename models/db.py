import json
import os
import sqlite3
from pathlib import Path

from flask import current_app, g


def get_db():
    if "db" not in g:
        db_path = current_app.config["DATABASE"]
        directory = os.path.dirname(db_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        connection = sqlite3.connect(db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=DELETE")  # Prevent WAL OneDrive issues
        g.db = connection
    return g.db


def safe_execute(db_func, *args, **kwargs):
    """Context manager wrapper for safe DB operations with logging."""
    try:
        return db_func(*args, **kwargs)
    except Exception as e:
        from utils.helpers import log_action
        log_action("DB SAFE EXECUTE ERROR", f"{db_func.__name__} - {str(e)}")
        raise


def close_db(_error=None):
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def init_db():
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS customers (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            phone TEXT,
            vehicle TEXT
        );

        CREATE TABLE IF NOT EXISTS admins (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            phone TEXT
        );

        CREATE TABLE IF NOT EXISTS bookings (
            booking_id TEXT PRIMARY KEY,
            customer_id TEXT,
            name TEXT NOT NULL,
            phone TEXT,
            vehicle TEXT NOT NULL,
            brand_model TEXT,
            service TEXT NOT NULL,
            date TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT,
            checked_in_at TEXT,
            completed_at TEXT,
            actual_visit_date TEXT,
            is_rescheduled INTEGER NOT NULL DEFAULT 0,
            whatsapp_sent INTEGER NOT NULL DEFAULT 0,
            msg_approved_sent INTEGER NOT NULL DEFAULT 0,
            msg_rejected_sent INTEGER NOT NULL DEFAULT 0,
            msg_checkedin_sent INTEGER NOT NULL DEFAULT 0,
            msg_completed_sent INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS slots (
            date TEXT PRIMARY KEY,
            total INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_id TEXT NOT NULL,
            action TEXT NOT NULL,
            performed_by TEXT,
            performed_by_id TEXT,
            details TEXT DEFAULT '{}',
            created_at TEXT NOT NULL
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_booking_id ON bookings(booking_id);
        CREATE INDEX IF NOT EXISTS idx_booking_status ON bookings(status);
        CREATE INDEX IF NOT EXISTS idx_booking_date ON bookings(date);
        CREATE INDEX IF NOT EXISTS idx_customer_id ON bookings(customer_id);
        CREATE INDEX IF NOT EXISTS idx_booking_phone_vehicle_date ON bookings(phone, vehicle, date);
        CREATE INDEX IF NOT EXISTS idx_audit_booking_id ON audit_logs(booking_id);
        CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs(action);
        CREATE INDEX IF NOT EXISTS idx_audit_created_at ON audit_logs(created_at);

        """
    )
    migrate_slots_table(db)
    migrate_bookings_table(db)
    seed_admins(db)
    migrate_json_data()
    migrate_customers_phone_unique(db)
    
    # NEW: Vehicles table + migration from customers.vehicle
    db.executescript("""
        CREATE TABLE IF NOT EXISTS vehicles (
            plate_number TEXT PRIMARY KEY,
            customer_id TEXT NOT NULL,
            brand TEXT DEFAULT '',
            model TEXT DEFAULT '',
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        );
    """)
    migrate_vehicles()
    db.commit()


def seed_admins(db):
    db.executemany(
        "INSERT OR IGNORE INTO admins (id, name, phone) VALUES (?, ?, ?)",
        [
            ("ADMIN001", "Owner", "9898135662"),
            ("ADMIN002", "Manager", ""),
        ],
    )


def _load_json_file(path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as file:
        try:
            return json.load(file)
        except json.JSONDecodeError:
            return default


def migrate_json_data():
    db = get_db()
    data_dir = Path(current_app.root_path) / "data"

    customers = _load_json_file(data_dir / "customers.json", [])
    for customer in customers:
        customer_id = (customer or {}).get("id", "").strip().upper()
        if not customer_id or customer_id.startswith("ADMIN"):
            continue
        db.execute(
            """
            INSERT OR IGNORE INTO customers (id, name, phone, vehicle)
            VALUES (?, ?, ?, ?)
            """,
            (
                customer_id,
                customer.get("name", "").strip(),
                customer.get("phone", "").strip(),
                customer.get("vehicle", "").strip().upper(),
            ),
        )

    bookings = _load_json_file(data_dir / "bookings.json", [])
    for booking in bookings:
        booking_id = (booking or {}).get("booking_id", "").strip().upper()
        if not booking_id:
            continue
        db.execute(
            """
            INSERT OR IGNORE INTO bookings (
                booking_id, customer_id, name, phone, vehicle, brand_model,
                service, date, status, created_at, checked_in_at, completed_at, whatsapp_sent
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                booking_id,
                booking.get("customer_id", "").strip().upper(),
                booking.get("name", "").strip(),
                booking.get("phone", "").strip(),
                booking.get("vehicle", "").strip().upper(),
                booking.get("brand_model", "").strip(),
                booking.get("service", "").strip(),
                booking.get("date", "").strip(),
                (booking.get("status", "pending") or "pending").strip().lower(),
                booking.get("created_at", "") or "",
                booking.get("checked_in_at"),
                booking.get("completed_at"),
                int(booking.get("whatsapp_sent", 0) or 0),
            ),
        )

    slots = _load_json_file(data_dir / "slots.json", {})
    if isinstance(slots, dict):
        for date, slot in slots.items():
            slot = slot or {}
            db.execute(
                """
                INSERT OR IGNORE INTO slots (date, total)
                VALUES (?, ?)
                """,
                (str(date).strip(), int(slot.get("total", 0) or 0)),
            )

    db.commit()


def migrate_slots_table(db):
    slot_columns = {
        row["name"]
        for row in db.execute("PRAGMA table_info(slots)").fetchall()
    }
    if "booked" not in slot_columns:
        return

    db.executescript(
        """
        ALTER TABLE slots RENAME TO slots_old;

        CREATE TABLE slots (
            date TEXT PRIMARY KEY,
            total INTEGER NOT NULL DEFAULT 0
        );

        INSERT INTO slots (date, total)
        SELECT date, total
        FROM slots_old;

        DROP TABLE slots_old;
        """
    )


# CHANGED: Enforce unique non-empty customer phone numbers for phone-based login.
def migrate_customers_phone_unique(db):
    seen_phones = set()
    rows = db.execute(
        """
        SELECT id, phone
        FROM customers
        WHERE TRIM(COALESCE(phone, '')) <> ''
        ORDER BY id ASC
        """
    ).fetchall()

    for row in rows:
        normalized_phone = str(row["phone"] or "").strip()
        if normalized_phone in seen_phones:
            db.execute("UPDATE customers SET phone = '' WHERE id = ?", (row["id"],))
            continue
        seen_phones.add(normalized_phone)

    db.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_customers_phone_unique
        ON customers(phone)
        WHERE phone IS NOT NULL AND phone <> ''
        """
    )


def migrate_bookings_table(db):
    booking_columns = {
        row["name"]
        for row in db.execute("PRAGMA table_info(bookings)").fetchall()
    }
    
    message_flags = ["msg_approved_sent", "msg_rejected_sent", "msg_checkedin_sent", "msg_completed_sent"]
    
    if "whatsapp_sent" not in booking_columns:
        db.execute(
            """
            ALTER TABLE bookings
            ADD COLUMN whatsapp_sent INTEGER NOT NULL DEFAULT 0
            """
        )

    if "actual_visit_date" not in booking_columns:
        db.execute(
            """
            ALTER TABLE bookings
            ADD COLUMN actual_visit_date TEXT
            """
        )

    if "is_rescheduled" not in booking_columns:
        db.execute(
            """
            ALTER TABLE bookings
            ADD COLUMN is_rescheduled INTEGER NOT NULL DEFAULT 0
            """
        )
    
    for flag in message_flags:
        if flag not in booking_columns:
            db.execute(
                f"""
                ALTER TABLE bookings
                ADD COLUMN {flag} INTEGER NOT NULL DEFAULT 0
                """
            )

    db.execute(
        """
        UPDATE bookings
        SET status = 'checked_in'
        WHERE status = 'in_garage'
        """
    )
    
    # Data migration for existing bookings
    db.execute("""
        UPDATE bookings 
        SET msg_approved_sent = 1 
        WHERE status IN ('checked_in', 'completed')
    """)
    
    db.execute("""
        UPDATE bookings 
        SET msg_checkedin_sent = 1 
        WHERE status = 'checked_in'
    """)
    
    db.execute("""
        UPDATE bookings 
        SET msg_completed_sent = 1 
        WHERE status = 'completed'
    """)
    
    # Reset rejected flag if any weird data
    db.execute("""
        UPDATE bookings 
        SET msg_rejected_sent = 0 
        WHERE status != 'rejected'
    """)

def migrate_vehicles():
    """NEW: Migrate customers.vehicle → normalized vehicles table"""
    db = get_db()
    rows = db.execute(
        "SELECT id, vehicle FROM customers WHERE vehicle IS NOT NULL AND TRIM(vehicle) <> ''"
    ).fetchall()
    
    for row in rows:
        plate_number = row["vehicle"].strip().upper()
        if plate_number:
            db.execute(
                """
                INSERT OR IGNORE INTO vehicles 
                (plate_number, customer_id, brand, model) 
                VALUES (?, ?, '', '')
                """,
                (plate_number, row["id"])
            )
    
    db.commit()


def init_app(app):
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()
