from urllib.parse import quote

from models.service_reminder_model import (
    build_service_reminder_message,
    count_due_service_reminders,
    get_due_service_reminders,
    get_service_reminder,
    mark_service_reminder_sent,
    snooze_service_reminder,
)
from utils.helpers import normalize_phone


def list_due_reminders():
    return get_due_service_reminders()


def list_due_reminders_local():
    from models.service_reminder_model import get_due_service_reminders_local

    return get_due_service_reminders_local()


def due_reminder_count():
    return count_due_service_reminders()


def due_reminder_count_local():
    from models.service_reminder_model import count_due_service_reminders_local

    return count_due_service_reminders_local()


def build_whatsapp_url_for_reminder(booking_id):
    reminder = get_service_reminder(booking_id)
    if not reminder:
        return None

    phone = normalize_phone(reminder.get("phone", ""))
    if len(phone) != 10:
        return None

    message = build_service_reminder_message(reminder)
    return f"https://wa.me/91{phone}?text={quote(message)}"


def mark_reminder_sent(booking_id):
    return mark_service_reminder_sent(booking_id)


def snooze_reminder(booking_id, days=7):
    return snooze_service_reminder(booking_id, days=days)
