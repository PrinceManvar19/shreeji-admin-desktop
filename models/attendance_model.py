"""Attendance model for worker daily attendance records."""

import datetime

from db_local import get_local_db as get_db
from utils.helpers import log_action


def _qdict(sql, params=()):
    conn = get_db()
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _qone(sql, params=()):
    conn = get_db()
    try:
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _exec(sql, params=()):
    conn = get_db()
    try:
        conn.execute(sql, params)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


VALID_STATUSES = {"present", "absent", "half_day", "leave", "holiday"}

STATUS_WEIGHTS = {
    "present": 1.0,
    "half_day": 0.5,
    "absent": 0.0,
    "leave": 0.0,
    "holiday": 0.0,
}


def _normalize_status(status, default="present"):
    status = (status or default).strip().lower()
    return status if status in VALID_STATUSES else default


def upsert_attendance(worker_id, attendance_date, status, notes=""):
    worker_id = worker_id.strip().upper()
    status = _normalize_status(status)
    notes = (notes or "").strip()

    from models.worker_model import get_worker
    worker = get_worker(worker_id)
    if not worker:
        return False, f"Worker {worker_id} not found"

    try:
        _exec("""
            INSERT INTO attendance_records (worker_id, date, status, notes)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (worker_id, date) DO UPDATE SET
                status = excluded.status,
                notes = excluded.notes
        """, (worker_id, attendance_date, status, notes))
        log_action("ATTENDANCE_SAVED", f"{worker_id} {attendance_date} {status}")
        return True, "Attendance saved"
    except Exception as e:
        log_action("ATTENDANCE_SAVE_ERROR", str(e))
        return False, f"Save failed: {e}"


def get_attendance_for_date(attendance_date):
    rows = _qdict("""
        SELECT ar.*, ar.date AS attendance_date, w.name, w.phone
        FROM attendance_records ar
        JOIN workers w ON ar.worker_id = w.id
        WHERE ar.date = ?
        ORDER BY w.name ASC
    """, (attendance_date,))
    return [dict(row) for row in rows]


def get_attendance_for_worker(worker_id, year=None, month=None):
    worker_id = worker_id.strip().upper()
    query = "SELECT *, date AS attendance_date FROM attendance_records WHERE worker_id = ?"
    params = [worker_id]

    if year:
        query += " AND substr(date, 1, 4) = ?"
        params.append(str(year))
    if month:
        query += " AND substr(date, 6, 2) = ?"
        params.append(f"{int(month):02d}")

    query += " ORDER BY date ASC"
    rows = _qdict(query, params)
    return [dict(row) for row in rows]


def calculate_month_attendance(worker_id, year, month):
    worker_id = worker_id.strip().upper()
    month_str = f"{int(month):02d}"
    date_prefix = f"{year}-{month_str}"

    rows = _qdict("""
        SELECT status FROM attendance_records
        WHERE worker_id = ? AND date LIKE ?
        ORDER BY date ASC
    """, (worker_id, date_prefix + "%"))

    total_records = len(rows)
    if total_records == 0:
        return {"total_days": 0, "attended_days": 0.0, "present_days": 0,
                "half_days": 0, "absent_days": 0, "leave_days": 0,
                "holiday_days": 0, "attendance_pct": 0.0}

    present_days = sum(1 for r in rows if r["status"] == "present")
    half_days = sum(1 for r in rows if r["status"] == "half_day")
    absent_days = sum(1 for r in rows if r["status"] == "absent")
    leave_days = sum(1 for r in rows if r["status"] == "leave")
    holiday_days = sum(1 for r in rows if r["status"] == "holiday")
    attended_days = present_days + (half_days * 0.5)
    attendance_pct = round((attended_days / total_records) * 100, 1) if total_records else 0.0

    return {"total_days": total_records, "attended_days": attended_days,
            "present_days": present_days, "half_days": half_days,
            "absent_days": absent_days, "leave_days": leave_days,
            "holiday_days": holiday_days, "attendance_pct": attendance_pct}


def get_today_summary():
    today = datetime.date.today().isoformat()
    rows = _qdict("""
        SELECT status, COUNT(*) as cnt
        FROM attendance_records
        WHERE date = ?
        GROUP BY status
    """, (today,))

    summary = {"present": 0, "absent": 0, "half_day": 0, "leave": 0, "holiday": 0, "total_workers": 0}
    status_counts = {row["status"]: row["cnt"] for row in rows}
    summary.update(status_counts)

    total_row = _qone("SELECT COUNT(*) as cnt FROM workers WHERE worker_status = 'active'")
    summary["total_workers"] = total_row["cnt"] if total_row else 0
    return summary


def bulk_save_attendance(records):
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
    query = """
        SELECT ar.*, ar.date AS attendance_date, w.name, w.phone
        FROM attendance_records ar
        JOIN workers w ON ar.worker_id = w.id
        WHERE 1=1
    """
    params = []
    if worker_id:
        query += " AND ar.worker_id = ?"
        params.append(worker_id.strip().upper())
    if year:
        query += " AND substr(ar.date, 1, 4) = ?"
        params.append(str(year))
    if month:
        query += " AND substr(ar.date, 6, 2) = ?"
        params.append(f"{int(month):02d}")
    if date_from:
        query += " AND ar.date >= ?"
        params.append(date_from)
    if date_to:
        query += " AND ar.date <= ?"
        params.append(date_to)

    query += " ORDER BY ar.date DESC"
    rows = _qdict(query, params)
    return [dict(row) for row in rows]
