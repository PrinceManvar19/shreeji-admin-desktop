"""
Audit log model for tracking all booking-related actions.
Provides a database-backed audit trail for compliance and debugging.
"""

import json
from datetime import datetime

from models.db import get_db


AUDIT_LOG_COLUMNS = """
    id, booking_id, action, performed_by, performed_by_id, 
    details, created_at
"""


def row_to_audit_log(row):
    """Convert a database row to an audit log dictionary."""
    log = dict(row)
    log["details"] = _parse_details(log.get("details", "{}"))
    return log


def _parse_details(details):
    """Parse JSON details string to dictionary."""
    if not details:
        return {}
    if isinstance(details, dict):
        return details
    try:
        return json.loads(details)
    except (json.JSONDecodeError, TypeError):
        return {"raw": str(details)}


def _serialize_details(details):
    """Serialize dictionary to JSON string."""
    if not details:
        return "{}"
    if isinstance(details, str):
        return details
    try:
        return json.dumps(details, default=str)
    except (TypeError, ValueError):
        return json.dumps({"raw": str(details)})


def log_audit_action(booking_id, action, performed_by=None, performed_by_id=None, details=None):
    """
    Log an audit action to the database.
    
    This function is wrapped in try/except to ensure it never breaks the main flow.
    
    Args:
        booking_id: The booking ID related to this action
        action: The action performed (e.g., 'booking_created', 'approved', 'checkin')
        performed_by: Name of the person who performed the action
        performed_by_id: ID of the person who performed the action
        details: Optional dictionary of additional details
    """
    try:
        db = get_db()
        db.execute(
            """
            INSERT INTO audit_logs (
                booking_id, action, performed_by, performed_by_id, 
                details, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
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
    except Exception as e:
        # Never break the main flow - log to text file as fallback
        from utils.helpers import log_action
        log_action(
            "AUDIT_LOG_FALLBACK",
            f"{booking_id} - {action} - {performed_by} - Error: {str(e)}"
        )


def get_audit_logs(booking_id=None, action=None, limit=50, offset=0):
    """
    Retrieve audit logs with optional filtering.
    
    Args:
        booking_id: Filter by booking ID
        action: Filter by action type
        limit: Maximum number of records to return
        offset: Number of records to skip
        
    Returns:
        list: Audit log dictionaries
    """
    conditions = []
    params = []
    
    if booking_id:
        conditions.append("booking_id = ?")
        params.append(booking_id)
    
    if action:
        conditions.append("action = ?")
        params.append(action.lower().strip())
    
    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
    
    # Add limit and offset to params
    params.extend([limit, offset])
    
    rows = get_db().execute(
        f"""
        SELECT {AUDIT_LOG_COLUMNS}
        FROM audit_logs
        {where_clause}
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
        """,
        tuple(params),
    ).fetchall()
    
    return [row_to_audit_log(row) for row in rows]


def get_audit_log_count(booking_id=None, action=None):
    """Get total count of audit logs matching filters."""
    conditions = []
    params = []
    
    if booking_id:
        conditions.append("booking_id = ?")
        params.append(booking_id)
    
    if action:
        conditions.append("action = ?")
        params.append(action.lower().strip())
    
    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
    
    row = get_db().execute(
        f"SELECT COUNT(*) AS total FROM audit_logs {where_clause}",
        tuple(params),
    ).fetchone()
    
    return row["total"] if row else 0


def get_latest_audit_action(booking_id, action):
    """Get the most recent audit log entry for a specific booking and action."""
    rows = get_db().execute(
        """
        SELECT id, booking_id, action, performed_by, performed_by_id, 
               details, created_at
        FROM audit_logs
        WHERE booking_id = ? AND action = ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (booking_id, action.lower().strip()),
    ).fetchall()
    
    return row_to_audit_log(rows[0]) if rows else None
