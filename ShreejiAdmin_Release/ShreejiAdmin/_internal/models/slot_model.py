from db_neon import query_dict, query_dict_one, execute_query
from utils.constants import ACTIVE_SLOT_STATUSES


def get_slots_map():
    rows = query_dict("SELECT date, total FROM slots ORDER BY date DESC")
    return {row["date"]: {"total": row["total"]} for row in rows}


def get_slots_map_local():
    from db_local import local_query

    placeholders = ", ".join(["?"] * len(ACTIVE_SLOT_STATUSES))
    rows = local_query(f"""
        SELECT s.date, s.total,
               COUNT(b.booking_id) AS booked
        FROM cache_slots s
        LEFT JOIN cache_bookings b
            ON b.date = s.date
            AND b.status IN ({placeholders})
        GROUP BY s.date, s.total
        ORDER BY s.date DESC
    """, ACTIVE_SLOT_STATUSES)
    return {
        row["date"]: {
            "total": row["total"],
            "booked": int(row["booked"] or 0),
            "available": max(0, row["total"] - int(row["booked"] or 0)),
        }
        for row in rows
    }


def get_slot(date):
    row = query_dict_one(
        "SELECT date, total FROM slots WHERE date = %s",
        (date,),
    )
    return dict(row) if row else None


def upsert_slot(date, total):
    execute_query(
        """
        INSERT INTO slots (date, total)
        VALUES (%s, %s)
        ON CONFLICT (date) DO UPDATE SET total = EXCLUDED.total
        """,
        (date, total),
    )


def update_slot_total(date, total):
    upsert_slot(date, total)
