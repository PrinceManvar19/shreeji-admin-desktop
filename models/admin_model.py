from models.db import get_db


def get_admin_by_id(admin_id):
    row = get_db().execute(
        "SELECT id, name, phone FROM admins WHERE id = ?",
        (admin_id,),
    ).fetchone()
    return dict(row) if row else None
