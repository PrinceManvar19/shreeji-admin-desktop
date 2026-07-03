import os
import sqlite3
import sys
from pathlib import Path


def _get_data_dir():
    if sys.platform == "win32":
        base = os.getenv("APPDATA") or Path.home()
    else:
        base = Path.home() / ".local" / "share"
    data_dir = Path(base) / "ShreejiAutoService"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


DATA_DIR = _get_data_dir()
DB_PATH = DATA_DIR / "garage.db"


CURRENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS admins (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    phone TEXT,
    password_hash TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS workers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    phone TEXT UNIQUE,
    monthly_salary REAL NOT NULL DEFAULT 0,
    worker_status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS attendance_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_id TEXT NOT NULL,
    date TEXT NOT NULL,
    status TEXT NOT NULL,
    check_in_time TEXT,
    check_out_time TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (worker_id, date),
    FOREIGN KEY (worker_id) REFERENCES workers (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS salary_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_id TEXT NOT NULL,
    month TEXT NOT NULL,
    year INTEGER NOT NULL,
    total_days INTEGER NOT NULL DEFAULT 0,
    attended_days REAL NOT NULL DEFAULT 0,
    per_day_salary REAL DEFAULT 0,
    base_salary REAL DEFAULT 0,
    bonus REAL DEFAULT 0,
    overtime REAL DEFAULT 0,
    commission REAL DEFAULT 0,
    gross_salary REAL DEFAULT 0,
    pocket_money_deduction REAL DEFAULT 0,
    monthly_advance_entry_count INTEGER DEFAULT 0,
    previous_pending_debt REAL DEFAULT 0,
    debt_recovery_deduction REAL DEFAULT 0,
    extra_salary REAL DEFAULT 0,
    remaining_debt_balance REAL DEFAULT 0,
    final_payable_salary REAL DEFAULT 0,
    net_salary REAL DEFAULT 0,
    total_salary REAL DEFAULT 0,
    salary_status TEXT NOT NULL DEFAULT 'finalized',
    payment_status TEXT DEFAULT 'pending',
    payment_method TEXT,
    paid_at TEXT,
    updated_at TEXT,
    pdf_path TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (worker_id, month, year),
    FOREIGN KEY (worker_id) REFERENCES workers (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS pocket_money_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_id TEXT NOT NULL,
    amount REAL NOT NULL,
    entry_date TEXT NOT NULL DEFAULT (date('now')),
    note TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (worker_id) REFERENCES workers (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS worker_debts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_id TEXT NOT NULL,
    debt_amount REAL NOT NULL,
    debt_date TEXT NOT NULL DEFAULT (date('now')),
    reason TEXT,
    remaining_balance REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (worker_id) REFERENCES workers (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS debt_recoveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    debt_id INTEGER NOT NULL,
    worker_id TEXT NOT NULL,
    salary_record_id INTEGER,
    recovery_amount REAL NOT NULL,
    recovery_date TEXT NOT NULL DEFAULT (date('now')),
    note TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (debt_id) REFERENCES worker_debts (id) ON DELETE CASCADE,
    FOREIGN KEY (worker_id) REFERENCES workers (id) ON DELETE CASCADE,
    FOREIGN KEY (salary_record_id) REFERENCES salary_records (id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS cache_bookings (
    booking_id TEXT PRIMARY KEY,
    customer_id TEXT,
    name TEXT NOT NULL,
    phone TEXT,
    vehicle TEXT,
    brand_model TEXT,
    service TEXT,
    date TEXT,
    status TEXT,
    created_at TEXT,
    checked_in_at TEXT,
    completed_at TEXT,
    actual_visit_date TEXT,
    is_rescheduled INTEGER DEFAULT 0,
    whatsapp_sent INTEGER DEFAULT 0,
    msg_approved_sent INTEGER DEFAULT 0,
    msg_rejected_sent INTEGER DEFAULT 0,
    msg_checkedin_sent INTEGER DEFAULT 0,
    msg_completed_sent INTEGER DEFAULT 0,
    service_reminder_sent INTEGER DEFAULT 0,
    reminder_sent_at TEXT,
    reminder_snooze_until TEXT,
    source TEXT DEFAULT 'customer_portal'
);

CREATE TABLE IF NOT EXISTS cache_customers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    phone TEXT,
    vehicle TEXT
);

CREATE TABLE IF NOT EXISTS cache_slots (
    date TEXT PRIMARY KEY,
    total INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_id TEXT NOT NULL,
    action TEXT NOT NULL,
    performed_by TEXT DEFAULT '',
    performed_by_id TEXT DEFAULT '',
    details TEXT DEFAULT '{}',
    created_at TEXT NOT NULL
);
"""


def get_local_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn, table_name):
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _table_columns(conn, table_name):
    if not _table_exists(conn, table_name):
        return {}
    return {row["name"]: dict(row) for row in conn.execute(f"PRAGMA table_info({table_name})")}


def _table_count(conn, table_name):
    if not _table_exists(conn, table_name):
        return 0
    return conn.execute(f"SELECT COUNT(*) AS count FROM {table_name}").fetchone()["count"]


def _archive_table(conn, table_name):
    if not _table_exists(conn, table_name):
        return

    suffix = 1
    archive_name = f"{table_name}_legacy"
    while _table_exists(conn, archive_name):
        suffix += 1
        archive_name = f"{table_name}_legacy_{suffix}"

    if _table_count(conn, table_name) == 0:
        conn.execute(f"DROP TABLE {table_name}")
    else:
        conn.execute(f"ALTER TABLE {table_name} RENAME TO {archive_name}")


def _archive_incompatible_tables(conn):
    admins = _table_columns(conn, "admins")
    if admins and str(admins.get("id", {}).get("type", "")).upper() != "TEXT":
        _archive_table(conn, "admins")

    workers = _table_columns(conn, "workers")
    if workers and (
        str(workers.get("id", {}).get("type", "")).upper() != "TEXT"
        or "monthly_salary" not in workers
        or "worker_status" not in workers
    ):
        for table_name in (
            "debt_recoveries",
            "worker_debts",
            "pocket_money_entries",
            "salary_records",
            "attendance_records",
            "workers",
        ):
            _archive_table(conn, table_name)
        return

    required_columns = {
        "salary_records": {"total_days", "attended_days", "total_salary", "salary_status", "final_payable_salary"},
        "pocket_money_entries": {"entry_date", "note"},
        "worker_debts": {"debt_amount", "remaining_balance", "status"},
        "debt_recoveries": {"worker_id", "recovery_amount", "note"},
    }
    for table_name, columns in required_columns.items():
        existing = set(_table_columns(conn, table_name))
        if existing and not columns.issubset(existing):
            _archive_table(conn, table_name)


def _ensure_column(conn, table_name, column_name, definition):
    columns = _table_columns(conn, table_name)
    if not columns or column_name in columns:
        return
    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def _upgrade_cache_tables(conn):
    cache_booking_columns = {
        "customer_id": "TEXT",
        "phone": "TEXT",
        "brand_model": "TEXT",
        "checked_in_at": "TEXT",
        "completed_at": "TEXT",
        "actual_visit_date": "TEXT",
        "is_rescheduled": "INTEGER DEFAULT 0",
        "whatsapp_sent": "INTEGER DEFAULT 0",
        "msg_approved_sent": "INTEGER DEFAULT 0",
        "msg_rejected_sent": "INTEGER DEFAULT 0",
        "msg_checkedin_sent": "INTEGER DEFAULT 0",
        "msg_completed_sent": "INTEGER DEFAULT 0",
        "service_reminder_sent": "INTEGER DEFAULT 0",
        "reminder_sent_at": "TEXT",
        "reminder_snooze_until": "TEXT",
        "source": "TEXT DEFAULT 'customer_portal'",
    }
    for column_name, definition in cache_booking_columns.items():
        _ensure_column(conn, "cache_bookings", column_name, definition)

    _ensure_column(conn, "cache_customers", "vehicle", "TEXT")
    _ensure_column(conn, "cache_slots", "total", "INTEGER NOT NULL DEFAULT 0")


def _seed_default_admins(conn):
    owner_phone = os.getenv("GARAGE_OWNER_PHONE", "").strip()
    conn.execute(
        """
        INSERT INTO admins (id, name, phone)
        VALUES (?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name = excluded.name,
            phone = CASE
                WHEN excluded.phone != '' THEN excluded.phone
                ELSE admins.phone
            END
        """,
        ("ADMIN001", "Owner", owner_phone),
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO admins (id, name, phone)
        VALUES (?, ?, ?)
        """,
        ("ADMIN002", "Manager", ""),
    )


def init_local_db():
    conn = get_local_db()
    try:
        _archive_incompatible_tables(conn)
        conn.executescript(CURRENT_SCHEMA)
        _upgrade_cache_tables(conn)
        _seed_default_admins(conn)
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    init_local_db()
    print("Local database initialized successfully.")


def local_query(sql, params=None):
    conn = get_local_db()
    try:
        rows = conn.execute(sql, params or ()).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def local_query_one(sql, params=None):
    conn = get_local_db()
    try:
        row = conn.execute(sql, params or ()).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()
