from datetime import datetime, timedelta
import re

from utils.constants import (
    STATUS_APPROVED,
    STATUS_CHECKED_IN,
    STATUS_COMPLETED,
    STATUS_PENDING,
    STATUS_REJECTED,
)


def normalize_phone(phone):
    normalized = (phone or "").strip().replace("+91", "")
    normalized = re.sub(r"\D", "", normalized)
    if len(normalized) > 10 and normalized.startswith("91"):
        normalized = normalized[-10:]
    return normalized


def get_status_display(status):
    status_map = {
        STATUS_PENDING: "Waiting for Approval",
        STATUS_APPROVED: "Approved",
        STATUS_CHECKED_IN: "In Progress",
        STATUS_REJECTED: "Rejected",
        STATUS_COMPLETED: "Completed",
    }
    normalized = (status or STATUS_PENDING).lower()
    return status_map.get(normalized, normalized.title())


def sort_bookings_newest_first(bookings):
    def booking_sort_key(booking):
        return booking.get("created_at") or booking.get("checked_in_at") or booking.get("date") or ""

    return sorted(bookings, key=booking_sort_key, reverse=True)


def get_today_date_string():
    return datetime.now().strftime("%Y-%m-%d")


def get_next_days(days=14):
    today = datetime.now().date()
    return [(today + timedelta(days=offset)).strftime("%Y-%m-%d") for offset in range(days)]


def parse_datetime(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def format_date_display(value):
    parsed = parse_datetime(value)
    if not parsed:
        return value or ""
    return parsed.strftime("%d-%m-%Y")


def format_datetime_display(value):
    parsed = parse_datetime(value)
    if not parsed:
        return value or ""
    return parsed.strftime("%d-%m-%Y %H:%M")


def log_action(action: str, details: str, performed_by=None):
    """Log an action to the centralized logs file."""
    import os
    from pathlib import Path

    base_dir = os.path.join(os.getenv("LOCALAPPDATA") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "GarageManagement")
    os.makedirs(base_dir, exist_ok=True)
    log_file = os.path.join(base_dir, "logs.txt")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    log_entry = f"[{timestamp}] {action.upper()} - {details}{' | by ' + performed_by if performed_by else ''}\n"
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(log_entry)
    except Exception:
        pass
