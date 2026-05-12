"""Attendance model for worker daily attendance records."""

import datetime
from models.db import get_db
from utils.helpers import log_action


VALID_STATUSES = {"present", "absent", "half_day", "leave", "holiday"}

STATUS_WEIGHTS = {
    "present": 1.0,
    "half_day": 0.5,
    "absent": 0.0,
    "leave": 0.0,
    "holiday": 0.0,   # holidays are not counted as worked days
}



def ensure_attendance_table():
    """Create attendance_records table if it doesn't exist."""
    db = get_db()
    columns = {row["name"] for row in db.execute("PRAGMA table_info(attendance_records)").fetchall()}
    if "id" not in columns:
        # Create a schema compatible with the project (and required by task).
        # Keep existing column 'status' while also providing 'attendance_status' and
        # check_in/check_out so downstream/legacy code won't crash.
        db.execute("""
            CREATE TABLE IF NOT EXISTS attendance_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                worker_id TEXT NOT NULL,
                attendance_date TEXT NOT NULL,

                -- Required columns (task spec)
                attendance_status TEXT NOT NULL DEFAULT 'present',
                check_in TEXT DEFAULT '',
                check_out TEXT DEFAULT '',

                -- Existing implementation columns (keep for compatibility)
                status TEXT NOT NULL DEFAULT 'present',

                notes TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (worker_id) REFERENCES workers(id),
                UNIQUE(worker_id, attendance_date)
            )
        """)
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_att_unique ON attendance_records(worker_id, attendance_date)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_att_date ON attendance_records(attendance_date)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_att_worker ON attendance_records(worker_id)")
        db.commit()
    else:
        # If the table exists but misses required columns, add them safely.
        # This must not delete existing data.
        required = {
            'attendance_status': "TEXT NOT NULL DEFAULT 'present'",
            'check_in': "TEXT DEFAULT ''",
            'check_out': "TEXT DEFAULT ''",
        }
        for col, ddl in required.items():
            if col not in columns:
                db.execute(f"ALTER TABLE attendance_records ADD COLUMN {col} {ddl}")
        # Ensure 'status' exists because current code uses it.
        if 'status' not in columns:
            db.execute("ALTER TABLE attendance_records ADD COLUMN status TEXT NOT NULL DEFAULT 'present'")
        db.commit()



def _normalize_status(status, default="present"):
    status = (status or default).strip().lower()
    return status if status in VALID_STATUSES else default


def upsert_attendance(worker_id, attendance_date, status, notes=""):
    """
    Insert or update a single attendance record.
    Returns (success, message).
    """
    ensure_attendance_table()
    worker_id = worker_id.strip().upper()
    status = _normalize_status(status)
    notes = (notes or "").strip()

    from models.worker_model import get_worker
    worker = get_worker(worker_id)
    if not worker:
        return False, f"Worker {worker_id} not found"

    try:
        get_db().execute("""
            INSERT INTO attendance_records (worker_id, attendance_date, status, notes)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(worker_id, attendance_date) DO UPDATE SET
                status = excluded.status,
                notes = excluded.notes,
                updated_at = CURRENT_TIMESTAMP
        """, (worker_id, attendance_date, status, notes))
        get_db().commit()
        log_action("ATTENDANCE_SAVED", f"{worker_id} {attendance_date} {status}")
        return True, "Attendance saved"
    except Exception as e:
        get_db().rollback()
        log_action("ATTENDANCE_SAVE_ERROR", str(e))
        return False, f"Save failed: {e}"


def get_attendance_for_date(attendance_date):
    """Get all attendance records for a given date with worker details."""
    ensure_attendance_table()
    rows = get_db().execute("""
        SELECT ar.*, w.name, w.phone
        FROM attendance_records ar
        JOIN workers w ON ar.worker_id = w.id
        WHERE ar.attendance_date = ?
        ORDER BY w.name ASC
    """, (attendance_date,)).fetchall()
    return [dict(row) for row in rows]


def get_attendance_for_worker(worker_id, year=None, month=None):
    """
    Get attendance records for a worker, optionally filtered by year/month.
    Returns list sorted by date ascending.
    """
    ensure_attendance_table()
    worker_id = worker_id.strip().upper()
    query = "SELECT * FROM attendance_records WHERE worker_id = ?"
    params = [worker_id]

    if year:
        query += " AND strftime('%Y', attendance_date) = ?"
        params.append(str(year))
    if month:
        query += " AND strftime('%m', attendance_date) = ?"
        params.append(f"{int(month):02d}")

    query += " ORDER BY attendance_date ASC"
    rows = get_db().execute(query, params).fetchall()
    return [dict(row) for row in rows]


def calculate_month_attendance(worker_id, year, month):
    """
    Calculate attendance totals for a worker in a given month.
    Returns dict with: total_days, attended_days (weighted), present_days,
    half_days, absent_days, leave_days, holiday_days, attendance_pct.
    """
    ensure_attendance_table()
    worker_id = worker_id.strip().upper()
    month_str = f"{int(month):02d}"
    date_prefix = f"{year}-{month_str}"

    rows = get_db().execute("""
        SELECT status FROM attendance_records
        WHERE worker_id = ? AND attendance_date LIKE ?
        ORDER BY attendance_date ASC
    """, (worker_id, date_prefix + "%")).fetchall()

    total_records = len(rows)
    if total_records == 0:
        return {
            "total_days": 0, "attended_days": 0.0,
            "present_days": 0, "half_days": 0,
            "absent_days": 0, "leave_days": 0, "holiday_days": 0,
            "attendance_pct": 0.0
        }

    present_days = sum(1 for r in rows if r["status"] == "present")
    half_days = sum(1 for r in rows if r["status"] == "half_day")
    absent_days = sum(1 for r in rows if r["status"] == "absent")
    leave_days = sum(1 for r in rows if r["status"] == "leave")
    holiday_days = sum(1 for r in rows if r["status"] == "holiday")

    attended_days = present_days + (half_days * 0.5)
    attendance_pct = round((attended_days / total_records) * 100, 1) if total_records > 0 else 0.0

    return {
        "total_days": total_records,
        "attended_days": attended_days,
        "present_days": present_days,
        "half_days": half_days,
        "absent_days": absent_days,
        "leave_days": leave_days,
        "holiday_days": holiday_days,
        "attendance_pct": attendance_pct
    }


def get_today_summary():
    """Return count stats for the current date."""
    ensure_attendance_table()
    today = datetime.date.today().isoformat()
    rows = get_db().execute("""
        SELECT status, COUNT(*) as cnt
        FROM attendance_records
        WHERE attendance_date = ?
        GROUP BY status
    """, (today,)).fetchall()

    summary = {"present": 0, "absent": 0, "half_day": 0, "leave": 0, "holiday": 0, "total_workers": 0}
    status_counts = {row["status"]: row["cnt"] for row in rows}
    summary.update(status_counts)

    total = get_db().execute(
        "SELECT COUNT(*) FROM workers WHERE worker_status = 'active'"
    ).fetchone()[0]
    summary["total_workers"] = total
    return summary


def bulk_save_attendance(records):
    """
    records: list of dicts with worker_id, attendance_date, status, notes.
    Returns (success_count, error_count).
    """
    ensure_attendance_table()
    ok, err = 0, 0
    for rec in records:
        ok_rec, _ = upsert_attendance(
            rec.get("worker_id"),
            rec.get("attendance_date"),
            rec.get("status", "present"),
            rec.get("notes", "")
        )
        if ok_rec:
            ok += 1
        else:
            err += 1
    return ok, err


def get_attendance_history(worker_id=None, year=None, month=None, date_from=None, date_to=None):
    """Get filtered attendance records for the history view."""
    ensure_attendance_table()
    query = """
        SELECT ar.*, w.name, w.phone
        FROM attendance_records ar
        JOIN workers w ON ar.worker_id = w.id
        WHERE 1=1
    """
    params = []
    if worker_id:
        query += " AND ar.worker_id = ?"
        params.append(worker_id.strip().upper())
    if year:
        query += " AND strftime('%Y', ar.attendance_date) = ?"
        params.append(str(year))
    if month:
        query += " AND strftime('%m', ar.attendance_date) = ?"
        params.append(f"{int(month):02d}")
    if date_from:
        query += " AND ar.attendance_date >= ?"
        params.append(date_from)
    if date_to:
        query += " AND ar.attendance_date <= ?"
        params.append(date_to)

    query += " ORDER BY ar.attendance_date DESC"
    rows = get_db().execute(query, params).fetchall()
    return [dict(row) for row in rows]