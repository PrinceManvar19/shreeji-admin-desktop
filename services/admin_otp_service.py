import hashlib
import os
import secrets
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage

from flask import session

from utils.helpers import log_action

OTP_SESSION_KEY = "admin_otp"
OTP_TTL_MINUTES = 10
OTP_LENGTH = 6


def _otp_email():
    return os.getenv("ADMIN_OTP_EMAIL", "").strip()


def _smtp_config():
    return {
        "host": os.getenv("SMTP_HOST", "").strip(),
        "port": int(os.getenv("SMTP_PORT", "587") or 587),
        "username": os.getenv("SMTP_USERNAME", "").strip(),
        "password": os.getenv("SMTP_PASSWORD", "").strip(),
        "from_email": os.getenv("SMTP_FROM_EMAIL", "").strip(),
        "use_tls": os.getenv("SMTP_USE_TLS", "1").strip().lower() not in ("0", "false", "no"),
    }


def admin_otp_destination():
    return _otp_email()


def mask_email(email):
    if not email or "@" not in email:
        return "configured admin email"
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        masked_local = local[:1] + "*"
    else:
        masked_local = local[:2] + "*" * max(1, len(local) - 2)
    return f"{masked_local}@{domain}"


def _hash_otp(otp):
    return hashlib.sha256(otp.encode("utf-8")).hexdigest()


def _generate_otp():
    upper = 10 ** OTP_LENGTH
    value = secrets.randbelow(upper)
    return f"{value:0{OTP_LENGTH}d}"


def _send_email(to_email, subject, body):
    config = _smtp_config()
    if not config["host"] or not config["from_email"]:
        return False, "SMTP is not configured."

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config["from_email"]
    message["To"] = to_email
    message.set_content(body)

    with smtplib.SMTP(config["host"], config["port"], timeout=12) as smtp:
        if config["use_tls"]:
            smtp.starttls()
        if config["username"]:
            smtp.login(config["username"], config["password"])
        smtp.send_message(message)

    return True, "OTP sent."


def start_admin_otp(user):
    to_email = _otp_email()
    if not to_email:
        return False, "ADMIN_OTP_EMAIL is not configured.", None

    otp = _generate_otp()
    expires_at = datetime.utcnow() + timedelta(minutes=OTP_TTL_MINUTES)
    session[OTP_SESSION_KEY] = {
        "otp_hash": _hash_otp(otp),
        "expires_at": expires_at.isoformat(),
        "attempts": 0,
        "user": {
            "id": user["id"],
            "name": user["name"],
            "phone": user.get("phone", ""),
            "role": "admin",
        },
    }

    subject = "Shreeji Auto Services Admin OTP"
    body = (
        f"Your Shreeji Auto Services admin login OTP is: {otp}\n\n"
        f"This code expires in {OTP_TTL_MINUTES} minutes.\n"
        "If you did not request this login, ignore this email."
    )

    try:
        sent, message = _send_email(to_email, subject, body)
    except Exception as error:
        log_action("ADMIN OTP EMAIL ERROR", str(error))
        sent = False
        message = "OTP email could not be sent."

    if not sent:
        log_action("ADMIN OTP DEV", f"{user['id']} OTP {otp} - {message}")
        if os.getenv("FLASK_DEBUG", "").lower() in ("1", "true") or os.getenv("RAILWAY_ENVIRONMENT") is None:
            message = f"OTP generated for local testing: {otp}"

    return True, message, mask_email(to_email)


def pending_admin_otp_user():
    data = session.get(OTP_SESSION_KEY)
    if not isinstance(data, dict):
        return None
    return data.get("user")


def verify_admin_otp(otp):
    data = session.get(OTP_SESSION_KEY)
    if not isinstance(data, dict):
        return False, "Please request a new OTP.", None

    try:
        expires_at = datetime.fromisoformat(data.get("expires_at", ""))
    except ValueError:
        session.pop(OTP_SESSION_KEY, None)
        return False, "Please request a new OTP.", None

    if datetime.utcnow() > expires_at:
        session.pop(OTP_SESSION_KEY, None)
        return False, "OTP expired. Please request a new OTP.", None

    attempts = int(data.get("attempts") or 0) + 1
    data["attempts"] = attempts
    session[OTP_SESSION_KEY] = data
    if attempts > 5:
        session.pop(OTP_SESSION_KEY, None)
        return False, "Too many OTP attempts. Please request a new OTP.", None

    if not secrets.compare_digest(data.get("otp_hash", ""), _hash_otp((otp or "").strip())):
        return False, "Invalid OTP. Please try again.", None

    user = data.get("user")
    session.pop(OTP_SESSION_KEY, None)
    if not user:
        return False, "Please request a new OTP.", None
    return True, "OTP verified.", user


def clear_admin_otp():
    session.pop(OTP_SESSION_KEY, None)
