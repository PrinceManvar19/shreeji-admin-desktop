from models.db import get_db


def get_slots_map():
    rows = get_db().execute("SELECT date, total FROM slots ORDER BY date DESC").fetchall()
    return {row["date"]: {"total": row["total"]} for row in rows}


def get_slot(date):
    row = get_db().execute(
        "SELECT date, total FROM slots WHERE date = ?",
        (date,),
    ).fetchone()
    return dict(row) if row else None


def upsert_slot(date, total):
    get_db().execute(
        """
        INSERT INTO slots (date, total)
        VALUES (?, ?)
        ON CONFLICT(date) DO UPDATE SET
            total = excluded.total
        """,
        (date, total),
    )


def update_slot_total(date, total):
    upsert_slot(date, total)
