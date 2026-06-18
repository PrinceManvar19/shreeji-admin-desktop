from decimal import Decimal, InvalidOperation

from db_local import get_local_db as get_db


def _qdict(sql, params=()):
    conn = get_db(); rows = conn.execute(sql, params).fetchall(); conn.close(); return [dict(r) for r in rows]


def _qone(sql, params=()):
    conn = get_db(); row = conn.execute(sql, params).fetchone(); conn.close(); return dict(row) if row else None


def _exec(sql, params=()):
    conn = get_db(); conn.execute(sql, params); conn.commit(); conn.close()


def _amount(value):
    try:
        amount = Decimal(str(value or "0"))
    except (InvalidOperation, TypeError, ValueError):
        amount = Decimal("0")
    return amount.quantize(Decimal("0.01"))


def add_pocket_money_entry(worker_id, amount, entry_date, note=""):
    amount = _amount(amount)
    if amount <= 0:
        return False, "Monthly advance amount must be greater than 0"

    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            INSERT INTO pocket_money_entries (worker_id, amount, entry_date, note)
            VALUES (?, ?, ?, ?)
        """, (worker_id, amount, entry_date, note))
        entry_id = cursor.lastrowid
        db.commit()
        return True, entry_id
    except Exception as error:
        db.rollback()
        return False, str(error)
    finally:
        cursor.close()
        db.close()


def get_pocket_money_entries(worker_id=None, month=None, year=None):
    where = []
    params = []

    if worker_id:
        where.append("p.worker_id = ?")
        params.append(worker_id)
    if month and year:
        where.append("substr(p.entry_date, 1, 7) = ?")
        params.append(f"{int(year):04d}-{int(month):02d}")

    where_sql = "WHERE " + " AND ".join(where) if where else ""
    return _qdict(f"""
        SELECT p.*, w.name AS worker_name
        FROM pocket_money_entries p
        JOIN workers w ON w.id = p.worker_id
        {where_sql}
        ORDER BY p.entry_date DESC, p.id DESC
    """, params)


def get_monthly_pocket_money_total(worker_id, month, year):
    row = _qone("""
        SELECT COALESCE(SUM(amount), 0) AS total
        FROM pocket_money_entries
        WHERE worker_id = ?
          AND substr(entry_date, 1, 7) = ?
    """, (worker_id, f"{int(year):04d}-{int(month):02d}"))
    return _amount(row["total"] if row else 0)


def get_monthly_pocket_money_count(worker_id, month, year):
    row = _qone("""
        SELECT COUNT(*) AS entry_count
        FROM pocket_money_entries
        WHERE worker_id = ?
          AND substr(entry_date, 1, 7) = ?
    """, (worker_id, f"{int(year):04d}-{int(month):02d}"))
    return int(row["entry_count"] if row else 0)


def add_worker_debt(worker_id, debt_amount, debt_date, reason=""):
    amount = _amount(debt_amount)
    if amount <= 0:
        return False, "Debt amount must be greater than 0"

    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            INSERT INTO worker_debts (worker_id, debt_amount, debt_date, reason, remaining_balance, status)
            VALUES (?, ?, ?, ?, ?, 'open')
        """, (worker_id, amount, debt_date, reason, amount))
        debt_id = cursor.lastrowid
        db.commit()
        return True, debt_id
    except Exception as error:
        db.rollback()
        return False, str(error)
    finally:
        cursor.close()
        db.close()


def get_worker_debts(worker_id=None, open_only=False):
    where = []
    params = []

    if worker_id:
        where.append("d.worker_id = ?")
        params.append(worker_id)
    if open_only:
        where.append("d.remaining_balance > 0")

    where_sql = "WHERE " + " AND ".join(where) if where else ""
    return _qdict(f"""
        SELECT d.*, w.name AS worker_name
        FROM worker_debts d
        JOIN workers w ON w.id = d.worker_id
        {where_sql}
        ORDER BY d.remaining_balance DESC, d.debt_date DESC, d.id DESC
    """, params)


def get_outstanding_debt_total(worker_id):
    row = _qone("""
        SELECT COALESCE(SUM(remaining_balance), 0) AS total
        FROM worker_debts
        WHERE worker_id = ? AND remaining_balance > 0
    """, (worker_id,))
    return _amount(row["total"] if row else 0)


def get_recovery_history(worker_id=None, debt_id=None):
    where = []
    params = []
    if worker_id:
        where.append("r.worker_id = ?")
        params.append(worker_id)
    if debt_id:
        where.append("r.debt_id = ?")
        params.append(debt_id)
    where_sql = "WHERE " + " AND ".join(where) if where else ""
    return _qdict(f"""
        SELECT r.*, w.name AS worker_name, d.reason AS debt_reason
        FROM debt_recoveries r
        JOIN workers w ON w.id = r.worker_id
        JOIN worker_debts d ON d.id = r.debt_id
        {where_sql}
        ORDER BY r.recovery_date DESC, r.id DESC
    """, params)


def apply_debt_recovery(worker_id, recovery_amount, recovery_date, salary_record_id=None, note="Salary recovery"):
    amount_left = _amount(recovery_amount)
    if amount_left <= 0:
        return True, Decimal("0.00")

    db = get_db()
    cursor = db.cursor()
    recovered = Decimal("0.00")
    try:
        cursor.execute("""
            SELECT id, remaining_balance
            FROM worker_debts
            WHERE worker_id = ? AND remaining_balance > 0
            ORDER BY debt_date ASC, id ASC
        """, (worker_id,))
        debts = cursor.fetchall()

        for debt in debts:
            if amount_left <= 0:
                break

            balance = _amount(debt["remaining_balance"])
            applied = min(balance, amount_left)
            new_balance = balance - applied

            cursor.execute("""
                INSERT INTO debt_recoveries (
                    debt_id, worker_id, salary_record_id, recovery_amount, recovery_date, note
                )
                VALUES (?, ?, ?, ?, ?, ?)
            """, (debt["id"], worker_id, salary_record_id, applied, recovery_date, note))

            cursor.execute("""
                UPDATE worker_debts
                SET remaining_balance = ?,
                    status = CASE WHEN ? <= 0 THEN 'closed' ELSE 'open' END
                WHERE id = ?
            """, (new_balance, new_balance, debt["id"]))

            recovered += applied
            amount_left -= applied

        db.commit()
        return True, recovered
    except Exception as error:
        db.rollback()
        return False, str(error)
    finally:
        cursor.close()
        db.close()


def get_monthly_advance_summary(worker_id=None, month=None, year=None):
    join_params = []
    where_params = []
    where = []
    if worker_id:
        where.append("w.id = ?")
        where_params.append(worker_id)
    where_sql = "WHERE " + " AND ".join(where) if where else ""
    month_filter = ""
    if month and year:
        month_filter = "AND substr(p.entry_date, 1, 7) = ?"
        join_params.append(f"{int(year):04d}-{int(month):02d}")

    return _qdict(f"""
        SELECT
            w.id AS worker_id,
            w.name AS worker_name,
            COALESCE(SUM(p.amount), 0) AS pocket_money_total,
            COALESCE((
                SELECT SUM(d.remaining_balance)
                FROM worker_debts d
                WHERE d.worker_id = w.id AND d.remaining_balance > 0
            ), 0) AS outstanding_debt
        FROM workers w
        LEFT JOIN pocket_money_entries p ON p.worker_id = w.id {month_filter}
        {where_sql}
        GROUP BY w.id, w.name
        ORDER BY w.name ASC
    """, join_params + where_params)
