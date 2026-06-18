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
