"""Audit log model for tracking all booking-related actions."""

import json
from datetime import datetime

from db_neon import get_neon_db as get_db, query_dict, query_dict_one, execute_query


AUDIT_LOG_COLUMNS = """
    id, booking_id, action, performed_by, performed_by_id,
    details, created_at
"""


def row_to_audit_log(row):
    log = dict(row)
    log["details"] = _parse_details(log.get("details", "{}"))
    return log


def _parse_details(details):
    if not details:
        return {}
    if isinstance(details, dict):
        return details
    try:
        return json.loads(details)
    except (json.JSONDecodeError, TypeError):
        return {"raw": str(details)}


def _serialize_details(details):
    if not details:
        return "{}"
    if isinstance(details, str):
        return details
    try:
        return json.dumps(details, default=str)
    except (TypeError, ValueError):
        return json.dumps({"raw": str(details)})


def log_audit_action(booking_id, action, performed_by=None, performed_by_id=None, details=None):
    try:
        db = get_db()
        cursor = db.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO audit_logs (
                    booking_id, action, performed_by, performed_by_id,
                    details, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    booking_id or "",
                    (action or "").lower().strip(),
                    performed_by or "",
                    performed_by_id or "",
                    _serialize_details(details),
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
            db.commit()
        finally:
            cursor.close()
    except Exception as e:
        from utils.helpers import log_action
        log_action("AUDIT_LOG_FALLBACK", f"{booking_id} - {action} - {performed_by} - Error: {str(e)}")


def get_audit_logs(booking_id=None, action=None, limit=50, offset=0):
    conditions = []
    params = []

    if booking_id:
        conditions.append("booking_id = %s")
        params.append(booking_id)
    if action:
        conditions.append("action = %s")
        params.append(action.lower().strip())

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
    params.extend([limit, offset])

    rows = query_dict(
        f"""
        SELECT {AUDIT_LOG_COLUMNS}
        FROM audit_logs
        {where_clause}
        ORDER BY created_at DESC
        LIMIT %s OFFSET %s
        """,
        tuple(params),
    )
    return [row_to_audit_log(row) for row in rows]


def get_audit_log_count(booking_id=None, action=None):
    conditions = []
    params = []
    if booking_id:
        conditions.append("booking_id = %s")
        params.append(booking_id)
    if action:
        conditions.append("action = %s")
        params.append(action.lower().strip())
    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
    row = query_dict_one(
        f"SELECT COUNT(*) AS total FROM audit_logs {where_clause}",
        tuple(params),
    )
    return row["total"] if row else 0


def get_latest_audit_action(booking_id, action):
    rows = query_dict(
        """
        SELECT id, booking_id, action, performed_by, performed_by_id,
               details, created_at
        FROM audit_logs
        WHERE booking_id = %s AND action = %s
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (booking_id, action.lower().strip()),
    )
    return row_to_audit_log(rows[0]) if rows else None
