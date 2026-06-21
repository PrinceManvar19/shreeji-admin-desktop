import json
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from pathlib import Path

from flask import current_app, g


def clean_database_url(database_url):
    cleaned = (database_url or "").strip()
    if (
        len(cleaned) >= 2
        and cleaned[0] == cleaned[-1]
        and cleaned[0] in ("'", '"')
    ):
        cleaned = cleaned[1:-1].strip()
    if cleaned.startswith("DATABASE_URL="):
        cleaned = cleaned.replace("DATABASE_URL=", "", 1).strip()
    if (
        len(cleaned) >= 2
        and cleaned[0] == cleaned[-1]
        and cleaned[0] in ("'", '"')
    ):
        cleaned = cleaned[1:-1].strip()
    return cleaned


def get_db():
    if "db" not in g:
        database_url = clean_database_url(
            current_app.config.get("DATABASE_URL") or os.getenv("DATABASE_URL")
        )

        if not database_url:
            raise ValueError(
                "DATABASE_URL environment variable not set. Add it to Railway "
                "Variables for the web service."
            )

        connection = psycopg2.connect(database_url, connect_timeout=5)
        g.db = connection

    return g.db


def safe_execute(db_func, *args, **kwargs):
    try:
        return db_func(*args, **kwargs)

    except Exception as e:
        from utils.helpers import log_action

        log_action(
            "DB SAFE EXECUTE ERROR",
            f"{db_func.__name__} - {str(e)}"
        )

        raise


def close_db(_error=None):
    connection = g.pop("db", None)

    if connection is not None:
        connection.close()


def query_dict(sql, params=None):
    db = get_db()

    cursor = db.cursor(cursor_factory=RealDictCursor)

    try:
        cursor.execute(sql, params or ())
        return cursor.fetchall()

    finally:
        cursor.close()


def query_dict_one(sql, params=None):
    db = get_db()

    cursor = db.cursor(cursor_factory=RealDictCursor)

    try:
        cursor.execute(sql, params or ())
        return cursor.fetchone()

    finally:
        cursor.close()


def execute_query(sql, params=None):
    db = get_db()

    cursor = db.cursor()

    try:
        cursor.execute(sql, params or ())
        db.commit()

    except psycopg2.Error:
        db.rollback()
        raise

    finally:
        cursor.close()


def _create_tables(cursor, db):
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
        CREATE TABLE IF NOT EXISTS admins (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            phone TEXT
        )
    """)

    cursor.execute("""
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
            msg_completed_sent INTEGER NOT NULL DEFAULT 0,
            source TEXT DEFAULT 'customer_portal'
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS slots (
            date TEXT PRIMARY KEY,
            total INTEGER NOT NULL DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id SERIAL PRIMARY KEY,
            booking_id TEXT NOT NULL,
            action TEXT NOT NULL,
            performed_by TEXT,
            performed_by_id TEXT,
            details TEXT DEFAULT '{}',
            created_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS workers (
            id TEXT PRIMARY KEY,
            name TEXT,
            phone TEXT,
            monthly_salary REAL,
            worker_status TEXT DEFAULT 'active'
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS salary_records (
            id SERIAL PRIMARY KEY,
            worker_id TEXT,
            month TEXT,
            year INTEGER,
            total_days INTEGER,
            attended_days REAL,
            per_day_salary REAL,
            base_salary REAL,
            bonus REAL,
            overtime REAL,
            commission REAL,
            gross_salary REAL DEFAULT 0,
            pocket_money_deduction REAL DEFAULT 0,
            monthly_advance_entry_count INTEGER DEFAULT 0,
            previous_pending_debt REAL DEFAULT 0,
            debt_recovery_deduction REAL DEFAULT 0,
            extra_salary REAL DEFAULT 0,
            remaining_debt_balance REAL DEFAULT 0,
            final_payable_salary REAL DEFAULT 0,
            net_salary REAL DEFAULT 0,
            total_salary REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (worker_id) REFERENCES workers(id),
            UNIQUE(worker_id, month, year)
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
        CREATE TABLE IF NOT EXISTS pocket_money_entries (
            id SERIAL PRIMARY KEY,
            worker_id TEXT NOT NULL,
            amount NUMERIC(10,2) NOT NULL,
            entry_date DATE NOT NULL DEFAULT CURRENT_DATE,
            note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (worker_id) REFERENCES workers(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS worker_debts (
            id SERIAL PRIMARY KEY,
            worker_id TEXT NOT NULL,
            debt_amount NUMERIC(10,2) NOT NULL,
            debt_date DATE NOT NULL DEFAULT CURRENT_DATE,
            reason TEXT,
            remaining_balance NUMERIC(10,2) NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (worker_id) REFERENCES workers(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS debt_recoveries (
            id SERIAL PRIMARY KEY,
            debt_id INTEGER NOT NULL,
            worker_id TEXT NOT NULL,
            salary_record_id INTEGER,
            recovery_amount NUMERIC(10,2) NOT NULL,
            recovery_date DATE NOT NULL DEFAULT CURRENT_DATE,
            note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (debt_id) REFERENCES worker_debts(id),
            FOREIGN KEY (worker_id) REFERENCES workers(id),
            FOREIGN KEY (salary_record_id) REFERENCES salary_records(id)
        )
    """)

    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_workers_phone_unique
        ON workers(phone)
        WHERE phone IS NOT NULL AND phone <> ''
    """)

    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_customers_phone_unique
        ON customers(phone)
        WHERE phone IS NOT NULL AND phone <> ''
    """)

    db.commit()

def _migrations_already_done(cursor, db):
    """Returns True if all one-time migrations have already run."""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS _migration_log (
            key TEXT PRIMARY KEY,
            ran_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("SELECT key FROM _migration_log WHERE key = 'v1_complete'")
    if cursor.fetchone() is not None:
        return True

    # Existing production databases may already be fully migrated before this
    # guard table existed. If the imported customer data is already present,
    # mark the one-time migrations complete to avoid startup-time full scans.
    cursor.execute("SELECT 1 FROM customer_vehicles LIMIT 1")
    if cursor.fetchone() is not None:
        _mark_migrations_done(cursor, db)
        return True

    return False


def _mark_migrations_done(cursor, db):
    cursor.execute("""
        INSERT INTO _migration_log (key) VALUES ('v1_complete')
        ON CONFLICT (key) DO NOTHING
    """)
    db.commit()


def init_db():
    db = get_db()

    cursor = db.cursor(cursor_factory=RealDictCursor)

    try:
        _create_tables(cursor, db)

        if not _migrations_already_done(cursor, db):
            migrate_workers_table(cursor, db)
            migrate_customers_table(cursor, db)
            migrate_bookings_table(cursor, db)
            migrate_salary_table(cursor, db)
            migrate_service_reminders(cursor, db)
            migrate_advance_tables(cursor, db)
            migrate_json_data(cursor, db)
            migrate_vehicles(cursor, db)
            migrate_customer_vehicles(cursor, db)
            _mark_migrations_done(cursor, db)

        seed_admins(cursor, db)

    except psycopg2.Error as e:
        db.rollback()
        raise e

    finally:
        cursor.close()


def seed_admins(cursor, db):
    owner_phone = os.getenv("GARAGE_OWNER_PHONE", "").strip()
    cursor.execute("""
        INSERT INTO admins (id, name, phone)
        VALUES (%s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET
            name = EXCLUDED.name,
            phone = CASE
                WHEN EXCLUDED.phone <> '' THEN EXCLUDED.phone
                ELSE admins.phone
            END
    """, (
        "ADMIN001",
        "Owner",
        owner_phone
    ))

    cursor.execute("""
        INSERT INTO admins (id, name, phone)
        VALUES (%s, %s, %s)
        ON CONFLICT (id) DO NOTHING
    """, (
        "ADMIN002",
        "Manager",
        ""
    ))

    db.commit()


def _load_json_file(path, default):
    if not path.exists():
        return default

    with path.open("r", encoding="utf-8") as file:
        try:
            return json.load(file)

        except json.JSONDecodeError:
            return default


def migrate_json_data(cursor, db):
    data_dir = Path(current_app.root_path) / "data"

    customers = _load_json_file(data_dir / "customers.json", [])

    for customer in customers:
        customer_id = (customer or {}).get("id", "").strip().upper()

        if not customer_id or customer_id.startswith("ADMIN"):
            continue

        phone = customer.get("phone", "").strip()

        existing_customer = None

        if phone:
            cursor.execute(
                "SELECT id FROM customers WHERE phone = %s",
                (phone,)
            )

            existing_customer = cursor.fetchone()

        if existing_customer:
            continue

        cursor.execute("""
            INSERT INTO customers (
                id,
                name,
                phone,
                vehicle
            )
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
        """, (
            customer_id,
            customer.get("name", "").strip(),
            phone,
            customer.get("vehicle", "").strip().upper(),
        ))

    bookings = _load_json_file(data_dir / "bookings.json", [])

    for booking in bookings:
        booking_id = (booking or {}).get("booking_id", "").strip().upper()

        if not booking_id:
            continue

        cursor.execute("""
            INSERT INTO bookings (
                booking_id,
                customer_id,
                name,
                phone,
                vehicle,
                brand_model,
                service,
                date,
                status,
                created_at,
                checked_in_at,
                completed_at,
                whatsapp_sent
            )
            VALUES (
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s
            )
            ON CONFLICT (booking_id) DO NOTHING
        """, (
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
        ))

    db.commit()


def migrate_bookings_table(cursor, db):
    cursor.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'bookings'
    """)

    existing_columns = {
        row["column_name"]
        for row in cursor.fetchall()
    }

    message_flags = [
        "msg_approved_sent",
        "msg_rejected_sent",
        "msg_checkedin_sent",
        "msg_completed_sent"
    ]

    columns_to_add = []

    for col in [
        "whatsapp_sent",
        "actual_visit_date",
        "is_rescheduled",
        "reminder_sent_at",
        "reminder_snooze_until",
        "service_reminder_sent"
    ] + message_flags:

        if col not in existing_columns:
            columns_to_add.append(col)

    for col in columns_to_add:
        if col in ("actual_visit_date", "reminder_sent_at", "reminder_snooze_until"):
            cursor.execute(
                "ALTER TABLE bookings ADD COLUMN actual_visit_date TEXT"
                if col == "actual_visit_date"
                else f"ALTER TABLE bookings ADD COLUMN {col} TEXT"
            )

        else:
            cursor.execute(
                f"ALTER TABLE bookings ADD COLUMN {col} INTEGER NOT NULL DEFAULT 0"
            )

    if "source" not in existing_columns:
        cursor.execute("ALTER TABLE bookings ADD COLUMN source TEXT DEFAULT 'customer_portal'")

    db.commit()


def migrate_customers_table(cursor, db):
    cursor.execute("""
        ALTER TABLE customers
        ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    """)
    db.commit()


def migrate_workers_table(cursor, db):
    cursor.execute("""
        ALTER TABLE workers
        ADD COLUMN IF NOT EXISTS worker_status TEXT DEFAULT 'active'
    """)

    cursor.execute("""
        UPDATE workers
        SET worker_status = 'active'
        WHERE worker_status IS NULL OR TRIM(worker_status) = ''
    """)


    db.commit()


def migrate_salary_table(cursor, db):
    salary_columns = {
        "salary_status": "TEXT NOT NULL DEFAULT 'finalized'",
        "payment_status": "TEXT DEFAULT 'pending'",
        "paid_at": "TEXT",
        "payment_method": "TEXT",
        "updated_at": "TEXT",
        "gross_salary": "REAL DEFAULT 0",
        "pocket_money_deduction": "REAL DEFAULT 0",
        "monthly_advance_entry_count": "INTEGER DEFAULT 0",
        "previous_pending_debt": "REAL DEFAULT 0",
        "debt_recovery_deduction": "REAL DEFAULT 0",
        "remaining_debt_balance": "REAL DEFAULT 0",
        "final_payable_salary": "REAL DEFAULT 0",
        "net_salary": "REAL DEFAULT 0",
    }

    for column, definition in salary_columns.items():
        cursor.execute(f"""
            ALTER TABLE salary_records
            ADD COLUMN IF NOT EXISTS {column} {definition}
        """)

    cursor.execute("""
        UPDATE salary_records
        SET gross_salary = COALESCE(NULLIF(gross_salary, 0), base_salary, total_salary, 0),
            final_payable_salary = COALESCE(NULLIF(final_payable_salary, 0), total_salary, 0),
            net_salary = COALESCE(NULLIF(net_salary, 0), total_salary, 0)
    """)

    db.commit()


def migrate_service_reminders(cursor, db):
    cursor.execute("""
        ALTER TABLE bookings
        ADD COLUMN IF NOT EXISTS reminder_sent_at TEXT
    """)
    cursor.execute("""
        ALTER TABLE bookings
        ADD COLUMN IF NOT EXISTS reminder_snooze_until TEXT
    """)
    cursor.execute("""
        ALTER TABLE bookings
        ADD COLUMN IF NOT EXISTS service_reminder_sent INTEGER NOT NULL DEFAULT 0
    """)
    db.commit()


def migrate_advance_tables(cursor, db):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pocket_money_entries (
            id SERIAL PRIMARY KEY,
            worker_id TEXT NOT NULL,
            amount NUMERIC(10,2) NOT NULL,
            entry_date DATE NOT NULL DEFAULT CURRENT_DATE,
            note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (worker_id) REFERENCES workers(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS worker_debts (
            id SERIAL PRIMARY KEY,
            worker_id TEXT NOT NULL,
            debt_amount NUMERIC(10,2) NOT NULL,
            debt_date DATE NOT NULL DEFAULT CURRENT_DATE,
            reason TEXT,
            remaining_balance NUMERIC(10,2) NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (worker_id) REFERENCES workers(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS debt_recoveries (
            id SERIAL PRIMARY KEY,
            debt_id INTEGER NOT NULL,
            worker_id TEXT NOT NULL,
            salary_record_id INTEGER,
            recovery_amount NUMERIC(10,2) NOT NULL,
            recovery_date DATE NOT NULL DEFAULT CURRENT_DATE,
            note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (debt_id) REFERENCES worker_debts(id),
            FOREIGN KEY (worker_id) REFERENCES workers(id),
            FOREIGN KEY (salary_record_id) REFERENCES salary_records(id)
        )
    """)

    db.commit()


def migrate_vehicles(cursor, db):
    cursor.execute("""
        SELECT id, vehicle
        FROM customers
        WHERE vehicle IS NOT NULL
        AND TRIM(vehicle) <> ''
    """)

    rows = cursor.fetchall()

    for row in rows:
        customer_id = row["id"]
        plate_number = row["vehicle"].strip().upper()

        if not plate_number:
            continue

        cursor.execute("""
            INSERT INTO vehicles (
                plate_number,
                customer_id,
                brand,
                model
            )
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (plate_number) DO NOTHING
        """, (
            plate_number,
            customer_id,
            '',
            ''
        ))

    db.commit()


def migrate_customer_vehicles(cursor, db):
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
        INSERT INTO customer_vehicles (customer_id, number_plate, brand_model)
        SELECT v.customer_id,
               UPPER(REGEXP_REPLACE(v.plate_number, '[^A-Za-z0-9]', '', 'g')),
               TRIM(CONCAT(COALESCE(NULLIF(v.brand, ''), ''), ' ', COALESCE(NULLIF(v.model, ''), '')))
        FROM vehicles v
        WHERE v.plate_number IS NOT NULL AND TRIM(v.plate_number) <> ''
        ON CONFLICT (number_plate) DO NOTHING
    """)

    cursor.execute("""
        INSERT INTO customer_vehicles (customer_id, number_plate, brand_model)
        SELECT c.id,
               UPPER(REGEXP_REPLACE(c.vehicle, '[^A-Za-z0-9]', '', 'g')),
               ''
        FROM customers c
        WHERE c.vehicle IS NOT NULL AND TRIM(c.vehicle) <> ''
        ON CONFLICT (number_plate) DO NOTHING
    """)

    db.commit()


def init_app(app):
    app.teardown_appcontext(close_db)

    with app.app_context():
        init_db()
