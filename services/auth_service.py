import os

from flask import session

from models.admin_model import get_admin_by_id, get_admin_by_phone
from models.customer_model import get_customer_by_id, get_customer_by_phone_or_id
from utils.token_store import load_token
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


def ensure_desktop_admin_session():
    if session.get("role") == "admin":
        ensure_session_user()
        return True

    token_data = load_token()
    if not token_data:
        return False

    admin_id = os.getenv("ADMIN_DESKTOP_ID", "ADMIN001").strip().upper() or "ADMIN001"
    admin_name = "Owner"
    admin_phone = ""

    try:
        admin = get_admin_by_id(admin_id)
        if admin:
            admin_name = admin["name"]
            admin_phone = admin.get("phone", "")
    except Exception as error:
        log_action("DESKTOP TOKEN ADMIN LOOKUP ERROR", str(error))

    set_user_session(admin_id, admin_name, "admin", admin_phone)
    session["desktop_auth_email"] = token_data.get("email", "")
    return True


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
    """
    Customer-only login by phone number.
    Admin login now uses dedicated /admin/login route with password verification.
    
    This function is for the public-facing login form and should NEVER verify
    admins without a password. It only handles customer phone login.
    """
    normalized_identifier = (identifier or "").strip().upper()
    normalized_phone = normalize_phone(identifier)

    # Only accept 10-digit phone numbers for customer login
    # Admin lookup removed - admins must use /admin/login with password
    if len(normalized_phone) == 10:
        try:
            customer = get_customer_by_phone_or_id(normalized_phone)
        except Exception as error:
            log_action("CUSTOMER LOGIN ERROR", str(error))
            return None

        if customer:
            return {
                "id": customer["id"],
                "name": customer["name"],
                "phone": customer.get("phone", ""),
                "role": "customer",
            }

    return None

