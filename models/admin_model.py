from db_neon import query_dict_one
import traceback
import os
from pathlib import Path
import json


def get_admin_by_id(admin_id):
    try:
        row = query_dict_one(
            "SELECT id, name, phone, password_hash FROM admins WHERE id = %s",
            (admin_id,),
        )
        if row is None:
            return None
        return dict(row) if row else None
    except Exception as e:
        # Log model errors for diagnostics
        log_file = Path(os.getcwd()) / "admin_login.log"
        log_entry = {
            "timestamp": __import__('datetime').datetime.now().isoformat(),
            "phase": "get_admin_by_id",
            "admin_id": admin_id,
            "error": {
                "type": type(e).__name__,
                "message": str(e),
                "traceback": traceback.format_exc(),
            }
        }
        try:
            with open(log_file, "a") as f:
                f.write(json.dumps(log_entry) + "\n")
        except Exception:
            pass
        raise


def get_admin_by_phone(phone):
    try:
        row = query_dict_one(
            "SELECT id, name, phone FROM admins WHERE phone = %s",
            (phone,),
        )
        if row is None:
            return None
        return dict(row) if row else None
    except Exception as e:
        # Log model errors for diagnostics
        log_file = Path(os.getcwd()) / "admin_login.log"
        log_entry = {
            "timestamp": __import__('datetime').datetime.now().isoformat(),
            "phase": "get_admin_by_phone",
            "phone": phone,
            "error": {
                "type": type(e).__name__,
                "message": str(e),
                "traceback": traceback.format_exc(),
            }
        }
        try:
            with open(log_file, "a") as f:
                f.write(json.dumps(log_entry) + "\n")
        except Exception:
            pass
        raise
