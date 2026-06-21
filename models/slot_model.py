from db_neon import query_dict, query_dict_one, execute_query
def get_slots_map():
    rows = query_dict("SELECT date, total FROM slots ORDER BY date DESC")
    return {row["date"]: {"total": row["total"]} for row in rows}


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


def update_slot(slot_id, date, time=None, max_bookings=None, status="open"):
    existing = get_slot(slot_id)
    if not existing:
        return {"success": False, "error": "Slot not found"}

    normalized_date = (date or "").strip()
    normalized_status = (status or "open").strip().lower()
    if normalized_status not in {"open", "closed"}:
        return {"success": False, "error": "Invalid slot status"}

    try:
        total = int(max_bookings)
    except (TypeError, ValueError):
        return {"success": False, "error": "Max bookings must be a valid number"}

    if not normalized_date:
        return {"success": False, "error": "Date is required"}
    if total < 0:
        return {"success": False, "error": "Max bookings cannot be negative"}

    if normalized_date != slot_id and get_slot(normalized_date):
        return {"success": False, "error": "A slot already exists for that date"}

    execute_query(
        """
        UPDATE slots
        SET date = %s, total = %s
        WHERE date = %s
        """,
        (normalized_date, total, slot_id),
    )
    return {"success": True, "slot": {"date": normalized_date, "total": total}}
