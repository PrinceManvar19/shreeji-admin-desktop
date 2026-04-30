from datetime import datetime

from models.db import get_db
from models.booking_model import count_bookings_for_slot
from models.slot_model import get_slot, get_slots_map, update_slot_total
from utils.helpers import get_next_days


def _build_slot_info(slot):
    if not slot:
        return None
    booked = count_bookings_for_slot(slot["date"])
    return {
        "date": slot["date"],
        "total": slot["total"],
        "booked": booked,
        "available": max(0, slot["total"] - booked),
    }


def get_next_14_days():
    slots = get_slots_for_admin()
    dates = []
    for date_str in get_next_days(14):
        slot_info = slots.get(date_str, {"total": 0, "booked": 0})
        label = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d/%B/%Y")
        dates.append(
            {
                "date": date_str,
                "label": label,
                "total": slot_info["total"],
                "booked": slot_info["booked"],
                "available": max(0, slot_info["total"] - slot_info["booked"]),
            }
        )
    return dates


def set_slot_total(date, total):
    slot = get_slot_availability(date)
    if slot and total < slot["booked"]:
        return False
    try:
        update_slot_total(date, total)
        get_db().commit()
    except Exception:
        get_db().rollback()
        return False
    return True


def has_available_slot(date):
    slot = get_slot_availability(date)
    return bool(slot and (slot["total"] - slot["booked"]) > 0)


def get_slots_for_admin():
    slots = {}
    for date, slot in get_slots_map().items():
        slot_info = _build_slot_info({"date": date, "total": slot["total"]})
        if slot_info:
            slots[date] = {
                "total": slot_info["total"],
                "booked": slot_info["booked"],
                "available": slot_info["available"],
            }
    return slots


def get_slot_availability(date):
    slot = get_slot(date)
    return _build_slot_info(slot)
