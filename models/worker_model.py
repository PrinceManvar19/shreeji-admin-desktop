from db_local import get_local_db as get_db
from utils.helpers import normalize_phone, log_action


def _qdict(sql, params=()):
    conn = get_db(); rows = conn.execute(sql, params).fetchall(); conn.close(); return [dict(r) for r in rows]


def _qone(sql, params=()):
    conn = get_db(); row = conn.execute(sql, params).fetchone(); conn.close(); return dict(row) if row else None


def _exec(sql, params=()):
    conn = get_db(); conn.execute(sql, params); conn.commit(); conn.close()


def generate_next_worker_id():
    rows = _qdict("SELECT id FROM workers WHERE id LIKE ?", ("WORK%",))
    used_numbers = set()
    for row in rows:
        suffix = str(row["id"] or "")[4:]
        if suffix.isdigit():
            used_numbers.add(int(suffix))
    next_number = 1001
    while next_number in used_numbers:
        next_number += 1
    return f"WORK{next_number}"


def get_all_workers():
    rows = _qdict(
        "SELECT id, name, phone, monthly_salary, worker_status FROM workers ORDER BY id ASC"
    )
    return [dict(row) for row in rows]


def get_worker(worker_id):
    row = _qone(
        "SELECT id, name, phone, monthly_salary, worker_status FROM workers WHERE id = ?",
        (worker_id,),
    )
    return dict(row) if row else None


def create_worker(worker_id, name, phone, monthly_salary, worker_status="active"):
    worker_id = (worker_id or "").strip().upper()
    name = (name or "").strip()
    norm_phone = normalize_phone(phone)
    worker_status = (worker_status or "active").strip().lower()
    try:
        monthly_salary = float(monthly_salary or 0)
    except (ValueError, TypeError):
        return False, "Monthly salary must be a number", None

    if not all([worker_id, name, norm_phone, monthly_salary is not None]):
        return False, "All fields are required", None
    if len(norm_phone) != 10:
        return False, "Phone must be exactly 10 digits", None
    if worker_status not in {"active", "inactive"}:
        worker_status = "active"

    existing = _qone("SELECT id FROM workers WHERE phone = ?", (norm_phone,))
    if existing:
        return False, "Phone number already registered", None

    db = get_db()
    cursor = None
    try:
        cursor = db.cursor()
        cursor.execute(
            "INSERT INTO workers (id, name, phone, monthly_salary, worker_status) VALUES (?, ?, ?, ?, ?)",
            (worker_id, name, norm_phone, monthly_salary, worker_status),
        )
        db.commit()
        return True, "", {"id": worker_id, "name": name, "phone": norm_phone,
                          "monthly_salary": monthly_salary, "worker_status": worker_status}
    except Exception as e:
        db.rollback()
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            return False, "Worker ID already exists", None
        log_action("WORKER CREATE ERROR", str(e))
        return False, "Failed to create worker", None
    finally:
        if cursor is not None:
            cursor.close()
        db.close()


def update_worker(worker_id, name, phone, monthly_salary, worker_status="active"):
    worker_id = (worker_id or "").strip().upper()
    name = (name or "").strip()
    norm_phone = normalize_phone(phone)
    worker_status = (worker_status or "active").strip().lower()
    try:
        monthly_salary = float(monthly_salary or 0)
    except (ValueError, TypeError):
        return False, "Monthly salary must be a number"

    if not worker_id or not name or not norm_phone:
        return False, "ID, name, phone required"
    if len(norm_phone) != 10:
        return False, "Phone must be 10 digits"
    if worker_status not in {"active", "inactive"}:
        return False, "Invalid worker status"

    existing = get_worker(worker_id)
    if not existing:
        return False, "Worker not found"

    phone_conflict = _qone(
        "SELECT id FROM workers WHERE phone = ? AND id != ?",
        (norm_phone, worker_id),
    )
    if phone_conflict:
        return False, "Phone already used by another worker"

    db = get_db()
    cursor = None
    try:
        cursor = db.cursor()
        cursor.execute(
            """
            UPDATE workers
            SET name = ?, phone = ?, monthly_salary = ?, worker_status = ?
            WHERE id = ?
            """,
            (name, norm_phone, monthly_salary, worker_status, worker_id),
        )
        db.commit()
        return True, ""
    except Exception as e:
        db.rollback()
        log_action("WORKER UPDATE ERROR", str(e))
        return False, "Update failed"
    finally:
        if cursor is not None:
            cursor.close()
        db.close()


def delete_worker(worker_id):
    worker_id = (worker_id or "").strip().upper()
    if not worker_id:
        return False, "ID required"
    existing = get_worker(worker_id)
    if not existing:
        return False, "Worker not found"
    db = get_db()
    cursor = None
    try:
        cursor = db.cursor()
        cursor.execute("DELETE FROM workers WHERE id = ?", (worker_id,))
        db.commit()
        return True, ""
    except Exception as e:
        db.rollback()
        log_action("WORKER DELETE ERROR", str(e))
        return False, "Delete failed"
    finally:
        if cursor is not None:
            cursor.close()
        db.close()
