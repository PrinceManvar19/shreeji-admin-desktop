import datetime
from decimal import Decimal

from db_local import get_local_db as get_db
from services.salary_service import calculate_salary
from utils.helpers import log_action


def _qdict(sql, params=()):
    conn = get_db(); rows = conn.execute(sql, params).fetchall(); conn.close(); return [dict(r) for r in rows]


def _qone(sql, params=()):
    conn = get_db(); row = conn.execute(sql, params).fetchone(); conn.close(); return dict(row) if row else None


def _exec(sql, params=()):
    conn = get_db(); conn.execute(sql, params); conn.commit(); conn.close()


VALID_SALARY_STATUSES = {"draft", "finalized", "paid"}


def _normalize_salary_status(status, default="finalized"):
    status = (status or default).strip().lower()
    return status if status in VALID_SALARY_STATUSES else default


def mark_salary_as_paid(record_id, admin_user_id=None):
    """Mark a salary record as paid and lock it from further edits."""
    record = get_salary_record(record_id)
    if not record:
        return False, "Salary record not found"

    current_status = (record.get("salary_status") or "").strip().lower()
    if current_status == "paid":
        return False, "This payroll record is already marked as PAID"

    now = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    try:
        _exec("""
            UPDATE salary_records
            SET salary_status = ?, payment_status = ?, paid_at = ?, updated_at = ?
            WHERE id = ?
        """, ("paid", "paid", now, now, record_id))
        log_action(
            "SALARY_RECORD_MARKED_PAID",
            f"ID {record_id} by {admin_user_id or 'unknown'}"
        )
        return True, "Salary record marked as paid and locked"
    except Exception as e:
        return False, f"Failed to mark as paid: {str(e)}"


def update_salary_payment_info(record_id, payment_method=None):
    """Save payment_method to an existing record."""
    if payment_method is None and payment_method != "":
        return

    if payment_method is not None and str(payment_method).strip():
        try:
            _exec("""
                UPDATE salary_records
                SET payment_method = ?
                WHERE id = ?
            """, (payment_method.strip(), record_id))
        except Exception:
            pass


def save_salary_record(
    worker_id,
    total_days,
    attended_days,
    bonus_val=0,
    bonus_pct=False,
    ot_val=0,
    ot_pct=False,
    comm_val=0,
    comm_pct=False,
    month=None,
    year=None,
    salary_status="finalized",
    payment_method=None,
    payment_status=None,
    debt_recovery_amount=0,
    extra_salary_amount=0,
    extra_salary_note="Extra salary advance",
):
    """
    Save salary calculation to salary_records.
    Prevents duplicate (worker_id, month, year).
    Returns (success, message, record_id).
    """
    worker_id = worker_id.strip().upper()
    if not worker_id:
        return False, "Worker ID required", None

    from models.worker_model import get_worker
    worker = get_worker(worker_id)
    if not worker:
        return False, f"Worker {worker_id} not found", None

    monthly_salary = Decimal(str(worker["monthly_salary"]))

    now = datetime.datetime.now()
    month = month or f"{now.month:02d}"
    year = year or now.year
    salary_status = _normalize_salary_status(salary_status)

    if payment_status is None:
        payment_status = "pending"
    if payment_method is None:
        payment_method = None

    if str(salary_status).strip().lower() == "paid" and str(payment_status).strip().lower() != "paid":
        payment_status = "paid"

    existing = _qone(
        "SELECT id FROM salary_records WHERE worker_id = ? AND month = ? AND year = ?",
        (worker_id, month, year)
    )
    if existing:
        return False, f"Salary record for {worker_id} {month}/{year} already exists", existing["id"]

    from models.advance_model import (
        apply_debt_recovery,
        get_monthly_pocket_money_count,
        get_monthly_pocket_money_total,
        get_outstanding_debt_total,
    )

    pocket_money_total = get_monthly_pocket_money_total(worker_id, month, year)
    pocket_money_count = get_monthly_pocket_money_count(worker_id, month, year)
    outstanding_before = get_outstanding_debt_total(worker_id)
    requested_recovery = Decimal(str(debt_recovery_amount or 0))
    estimated_base = (monthly_salary / Decimal(str(max(total_days, 1)))) * Decimal(str(attended_days))
    max_recovery_from_pay = max(estimated_base - pocket_money_total, Decimal("0"))
    debt_recovery = min(max(requested_recovery, Decimal("0")), outstanding_before, max_recovery_from_pay)

    try:
        calc_result = calculate_salary(
            monthly_salary=float(monthly_salary),
            total_days=total_days,
            attended_days=attended_days,
            bonus=(0, False),
            overtime=(0, False),
            commission=(0, False),
            pocket_money_deduction=float(pocket_money_total),
            debt_recovery_deduction=float(debt_recovery),
        )
    except Exception as e:
        return False, f"Calculation error: {str(e)}", None

    per_day = calc_result["per_day_salary"]
    base = calc_result["base_salary"]
    bonus_amt = Decimal("0")
    ot_amt = Decimal("0")
    comm_amt = Decimal("0")
    gross = calc_result["gross_salary"]
    total = calc_result["total_salary"]

    extra_salary = Decimal(str(extra_salary_amount or 0)).quantize(Decimal("0.01"))
    if extra_salary < 0:
        extra_salary = Decimal("0")
    final_payable_salary = total + extra_salary
    net_salary = total + extra_salary
    remaining_debt_balance = max(outstanding_before - debt_recovery, Decimal("0")) + extra_salary

    paid_at = None
    if payment_status and str(payment_status).strip().lower() == "paid":
        paid_at = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    db = get_db()
    cursor = None
    try:
        cursor = db.cursor()
        cursor.execute("""
            INSERT INTO salary_records (
                worker_id, month, year, total_days, attended_days,
                per_day_salary, base_salary, bonus, overtime, commission,
                gross_salary, pocket_money_deduction, monthly_advance_entry_count,
                previous_pending_debt, debt_recovery_deduction, extra_salary,
                remaining_debt_balance, final_payable_salary, net_salary, total_salary,
                salary_status, payment_status, payment_method, paid_at
            )
            VALUES (
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?
            )
        """, (
            worker_id, month, year, total_days, attended_days,
            float(per_day), float(base), float(bonus_amt), float(ot_amt), float(comm_amt),
            float(gross), float(pocket_money_total), pocket_money_count,
            float(outstanding_before), float(debt_recovery), float(extra_salary),
            float(remaining_debt_balance), float(final_payable_salary), float(net_salary), float(total),
            salary_status, payment_status, payment_method, paid_at,
        ))
        record_id = cursor.lastrowid
        db.commit()
    except Exception as e:
        db.rollback()
        log_action("SALARY_RECORD_SAVE_ERROR", str(e))
        return False, f"Save failed: {str(e)}", None
    finally:
        if cursor is not None:
            cursor.close()
        db.close()

    if debt_recovery > 0 and record_id:
        ok, recovered = apply_debt_recovery(
            worker_id,
            debt_recovery,
            f"{year}-{int(month):02d}-01",
            salary_record_id=record_id,
            note=f"Recovered from salary {month}/{year}",
        )
        if ok:
            remaining_after = get_outstanding_debt_total(worker_id)
            _exec("""
                UPDATE salary_records
                SET debt_recovery_deduction = ?,
                    remaining_debt_balance = ?
                WHERE id = ?
            """, (float(recovered), float(remaining_after), record_id))

    if extra_salary > 0 and record_id:
        from models.advance_model import add_worker_debt
        debt_date = datetime.date.today().isoformat()
        added, debt_id = add_worker_debt(
            worker_id=worker_id,
            debt_amount=float(extra_salary),
            debt_date=debt_date,
            reason=extra_salary_note or "Extra salary advance",
        )
        if added:
            updated_total_debt = get_outstanding_debt_total(worker_id)
            _exec("""
                UPDATE salary_records
                SET remaining_debt_balance = ?
                WHERE id = ?
            """, (float(updated_total_debt), record_id))

    log_action("SALARY_RECORD_SAVED", f"{worker_id} {month}/{year} total={total:.2f}")
    return True, "Salary record saved successfully", record_id


def get_salary_records(worker_id=None, month=None, year=None):
    """Get salary records (filter optional) with worker details JOINed."""
    query = """
        SELECT sr.*, w.name as worker_name, w.phone as worker_phone, w.monthly_salary as worker_monthly_salary
        FROM salary_records sr
        JOIN workers w ON sr.worker_id = w.id
    """
    params = []
    where = []

    if worker_id:
        where.append("sr.worker_id = ?")
        params.append(worker_id)
    if month:
        where.append("sr.month = ?")
        params.append(month)
    if year:
        where.append("sr.year = ?")
        params.append(year)

    if where:
        query += " WHERE " + " AND ".join(where)

    query += " ORDER BY sr.year DESC, sr.month DESC"

    rows = _qdict(query, params)
    return rows


def get_salary_record(record_id):
    """Get single salary record with worker details."""
    row = _qone("""
        SELECT sr.*, w.name as worker_name, w.phone as worker_phone, w.monthly_salary as worker_monthly_salary
        FROM salary_records sr
        JOIN workers w ON sr.worker_id = w.id
        WHERE sr.id = ?
    """, (record_id,))
    return row


def update_salary_record(record_id, total_days=None, attended_days=None, bonus_val=None, bonus_pct=None, ot_val=None, ot_pct=None, comm_val=None, comm_pct=None, debt_recovery_amount=None, extra_salary_amount=None, extra_salary_note="Extra salary advance", salary_status=None):
    """
    Update salary record fields. Recalculates all salary values.
    Returns (success, message).

    Backend security: if the record is already PAID, reject updates.
    """
    record = get_salary_record(record_id)
    if not record:
        return False, "Salary record not found"

    current_status = (record.get("salary_status") or "").strip().lower()
    if current_status == "paid":
        return False, "This payroll record has been marked as PAID and is locked from further editing."

    worker_id = record["worker_id"]
    worker_monthly = record.get("worker_monthly_salary") or 0

    total_days = record["total_days"] if total_days is None else total_days
    attended_days = record["attended_days"] if attended_days is None else attended_days

    bonus_val = record.get("bonus") if bonus_val is None else bonus_val
    bonus_pct = False if bonus_pct is None else bonus_pct
    ot_val = record.get("overtime") if ot_val is None else ot_val
    ot_pct = False if ot_pct is None else ot_pct
    comm_val = record.get("commission") if comm_val is None else comm_val
    comm_pct = False if comm_pct is None else comm_pct

    monthly_advance = Decimal(str(record.get("pocket_money_deduction") or 0))
    previous_pending_debt = Decimal(str(
        record.get("previous_pending_debt")
        if record.get("previous_pending_debt") not in (None, "")
        else Decimal(str(record.get("remaining_debt_balance") or 0)) + Decimal(str(record.get("debt_recovery_deduction") or 0))
    ))
    inferred_previous_debt = Decimal(str(record.get("remaining_debt_balance") or 0)) + Decimal(str(record.get("debt_recovery_deduction") or 0))
    if previous_pending_debt == 0 and inferred_previous_debt > 0:
        previous_pending_debt = inferred_previous_debt
    requested_recovery = Decimal(str(
        record.get("debt_recovery_deduction") if debt_recovery_amount is None else debt_recovery_amount
    ))
    debt_recovery = min(max(requested_recovery, Decimal("0")), max(previous_pending_debt, Decimal("0")))

    previous_extra_salary = Decimal(str(record.get("extra_salary") or 0))
    extra_salary = Decimal(str(previous_extra_salary if extra_salary_amount is None else extra_salary_amount or 0))
    if extra_salary < 0:
        extra_salary = Decimal("0")

    salary_status = _normalize_salary_status(salary_status, record.get("salary_status") or "finalized")

    try:
        calc_result = calculate_salary(
            monthly_salary=float(worker_monthly),
            total_days=total_days,
            attended_days=attended_days,
            bonus=(bonus_val, bonus_pct),
            overtime=(ot_val, ot_pct),
            commission=(comm_val, comm_pct),
            pocket_money_deduction=monthly_advance,
            debt_recovery_deduction=debt_recovery,
        )
    except Exception as e:
        return False, f"Calculation error: {str(e)}"

    per_day = calc_result["per_day_salary"]
    base = calc_result["base_salary"]
    bonus_amt = calc_result["bonus_amount"]
    ot_amt = calc_result["overtime_amount"]
    comm_amt = calc_result["commission_amount"]
    gross = calc_result.get("gross_salary", base)
    total = calc_result["total_salary"]

    final_payable_salary = total + extra_salary
    net_salary = total + extra_salary
    remaining_debt_balance = max(previous_pending_debt - debt_recovery, Decimal("0")) + extra_salary
    now = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    set_parts = [
        "total_days = ?",
        "attended_days = ?",
        "per_day_salary = ?",
        "base_salary = ?",
        "bonus = ?",
        "overtime = ?",
        "commission = ?",
        "gross_salary = ?",
        "total_salary = ?",
        "salary_status = ?",
        "final_payable_salary = ?",
        "extra_salary = ?",
        "debt_recovery_deduction = ?",
        "remaining_debt_balance = ?",
        "previous_pending_debt = ?",
        "net_salary = ?",
        "updated_at = ?",
    ]
    params = [
        total_days,
        attended_days,
        float(per_day),
        float(base),
        float(bonus_amt),
        float(ot_amt),
        float(comm_amt),
        float(gross),
        float(total),
        salary_status,
        float(final_payable_salary),
        float(extra_salary),
        float(debt_recovery),
        float(remaining_debt_balance),
        float(previous_pending_debt),
        float(net_salary),
        now,
    ]

    if salary_status == "paid":
        set_parts.append("payment_status = 'paid'")
        set_parts.append("paid_at = ?")
        params.append(now)

    try:
        sql = f"UPDATE salary_records SET {', '.join(set_parts)} WHERE id = ?"
        params.append(record_id)
        _exec(sql, tuple(params))

        if extra_salary > previous_extra_salary:
            debt_diff = extra_salary - previous_extra_salary
            if debt_diff > 0:
                from models.advance_model import add_worker_debt, get_outstanding_debt_total
                debt_date = datetime.date.today().isoformat()
                added, debt_id = add_worker_debt(
                    worker_id=worker_id,
                    debt_amount=float(debt_diff),
                    debt_date=debt_date,
                    reason=extra_salary_note or "Extra salary advance",
                )
                if added:
                    updated_total_debt = get_outstanding_debt_total(worker_id)
                    _exec(
                        "UPDATE salary_records SET remaining_debt_balance = ? WHERE id = ?",
                        (float(updated_total_debt), record_id)
                    )

        log_action("SALARY_RECORD_UPDATED", f"ID {record_id} total={total:.2f}")
        return True, "Record updated successfully"
    except Exception as e:
        log_action("SALARY_RECORD_UPDATE_ERROR", str(e))
        return False, f"Update failed: {str(e)}"


def delete_salary_record(record_id):
    """Delete a salary record."""
    try:
        _exec("DELETE FROM salary_records WHERE id = ?", (record_id,))
        log_action("SALARY_RECORD_DELETED", f"ID {record_id}")
        return True, "Salary record deleted"
    except Exception as e:
        log_action("SALARY_RECORD_DELETE_ERROR", str(e))
        return False, f"Delete failed: {str(e)}"
