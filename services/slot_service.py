from datetime import datetime

from db_neon import get_neon_db as get_db, query_dict
from models.booking_model import count_bookings_for_slot
from models.slot_model import get_slot, update_slot_total
from utils.constants import ACTIVE_SLOT_STATUSES
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
    placeholders = ", ".join(["%s"] * len(ACTIVE_SLOT_STATUSES))
    rows = query_dict(
        f"""
        SELECT
            s.date,
            s.total,
            COUNT(b.booking_id) AS booked
        FROM slots s
        LEFT JOIN bookings b
          ON b.date = s.date
         AND b.status IN ({placeholders})
        GROUP BY s.date, s.total
        ORDER BY s.date DESC
        """,
        ACTIVE_SLOT_STATUSES,
    )

    return {
        row["date"]: {
            "total": row["total"],
            "booked": int(row["booked"] or 0),
            "available": max(0, row["total"] - int(row["booked"] or 0)),
        }
        for row in rows
    }


def get_slots_for_admin_local():
    from models.slot_model import get_slots_map_local

    return get_slots_map_local()


def get_slot_availability(date):
    slot = get_slot(date)
    return _build_slot_info(slot)
