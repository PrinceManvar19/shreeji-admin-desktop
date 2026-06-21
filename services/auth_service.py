from flask import session

from models.admin_model import get_admin_by_id, get_admin_by_phone
from models.customer_model import get_customer_by_id, get_customer_by_phone_or_id
from utils.helpers import log_action, normalize_phone


def set_user_session(user_id, name, role, phone=""):
    session["customer_id"] = user_id
    session["name"] = name
    session["phone"] = phone or ""
    session["role"] = role
    session["user"] = {
        "id": user_id,
        "name": name,
        "phone": phone or "",
        "role": role,
    }


def ensure_session_user():
    if "customer_id" not in session or "name" not in session:
        return

    role = session.get("role", "customer")
    expected = {
        "id": session["customer_id"],
        "name": session["name"],
        "phone": session.get("phone", ""),
        "role": role,
    }
    if not isinstance(session.get("user"), dict) or session["user"] != expected:
        session["user"] = expected


def login_user_by_id(user_id):
    normalized_id = user_id.strip().upper()
    admin = get_admin_by_id(normalized_id)
    if admin:
        return {"id": admin["id"], "name": admin["name"], "phone": admin.get("phone", ""), "role": "admin"}

    customer = get_customer_by_id(normalized_id)
    if customer:
        return {
            "id": customer["id"],
            "name": customer["name"],
            "phone": customer.get("phone", ""),
            "role": "customer",
        }

    return None


# CHANGED: Login can now resolve a user from phone number or existing Customer/Admin ID.

def login_user_by_identifier(identifier):
    normalized_identifier = (identifier or "").strip().upper()

    # Check admin first for ADMIN* IDs.
    if normalized_identifier.startswith("ADMIN"):
        try:
            admin = get_admin_by_id(normalized_identifier)
            if admin:
                return {"id": admin["id"], "name": admin["name"], "phone": admin.get("phone", ""), "role": "admin"}
        except Exception as error:
            log_action("ADMIN LOGIN ERROR", str(error))
        return None

    # Check admin by registered phone before treating the value as a customer login.
    normalized_phone = normalize_phone(identifier)
    if len(normalized_phone) == 10:
        try:
            admin = get_admin_by_phone(normalized_phone)
            if admin:
                return {"id": admin["id"], "name": admin["name"], "phone": admin.get("phone", ""), "role": "admin"}
        except Exception as error:
            log_action("ADMIN PHONE LOGIN ERROR", str(error))

    # Phone or customer ID.
    try:
        customer = get_customer_by_phone_or_id(normalized_identifier)
    except Exception as error:
        log_action("LOGIN ERROR", str(error))
        return None

    if customer:
        return {
            "id": customer["id"],
            "name": customer["name"],
            "phone": customer.get("phone", ""),
            "role": "customer",
        }

    return None

