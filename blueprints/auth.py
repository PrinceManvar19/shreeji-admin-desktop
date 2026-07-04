import os
from datetime import datetime, timedelta, timezone

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from utils.auth_helpers import hash_password, verify_password
from utils.email_utils import generate_otp, hash_otp, send_otp_email
from utils.token_store import delete_token, is_authenticated, save_token


auth_bp = Blueprint("auth", __name__)

RATE_LIMIT = {}


def is_rate_limited(email):
    now = datetime.now(timezone.utc)
    window = now - timedelta(minutes=15)
    timestamps = [timestamp for timestamp in RATE_LIMIT.get(email, []) if timestamp > window]
    RATE_LIMIT[email] = timestamps
    return len(timestamps) >= 5


@auth_bp.route("/admin/login", methods=["GET", "POST"])
def login():
    if is_authenticated():
        return redirect(url_for("admin.admin"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()

        from db_neon import get_db_connection

        try:
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT password_hash FROM admin_users WHERE email = %s",
                        (email,),
                    )
                    row = cur.fetchone()
        except Exception:
            flash("Database error. Check internet connection.", "danger")
            return render_template("admin/login.html")

        if not row or not verify_password(password, row[0]):
            flash("Invalid email or password.", "danger")
            return render_template("admin/login.html")

        save_token(email)
        session.clear()
        session["admin_logged_in"] = True
        session["admin_email"] = email
        return redirect(url_for("admin.admin"))

    return render_template("admin/login.html")


@auth_bp.route("/admin/logout")
def logout():
    delete_token()
    session.clear()
    return redirect(url_for("auth.login"))


# Compatibility redirects for existing admin guards/templates. The former OTP
# handlers are gone; these endpoints now lead to the password-based flow.
@auth_bp.route("/desktop/login", endpoint="desktop_login")
def desktop_login_redirect():
    return redirect(url_for("auth.login"))


@auth_bp.route("/desktop/logout", endpoint="desktop_logout")
def desktop_logout_redirect():
    return logout()


@auth_bp.route("/admin/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        admin_email = os.environ.get("ADMIN_EMAIL", "").strip().lower()

        if email != admin_email or is_rate_limited(email):
            flash("If this email is registered, a reset code has been sent.", "info")
            return render_template("admin/forgot_password.html")

        otp_code, code_hash = generate_otp()
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)

        from db_neon import get_db_connection

        try:
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE otp_tokens SET used=TRUE WHERE email=%s AND used=FALSE",
                        (email,),
                    )
                    cur.execute(
                        "INSERT INTO otp_tokens (email, code_hash, expires_at) VALUES (%s,%s,%s)",
                        (email, code_hash, expires_at),
                    )
                conn.commit()
        except Exception:
            flash("Database error. Please try again.", "danger")
            return render_template("admin/forgot_password.html")

        RATE_LIMIT.setdefault(email, []).append(datetime.now(timezone.utc))

        try:
            send_otp_email(email, otp_code)
        except Exception:
            flash("Failed to send email. Check connection.", "danger")
            return render_template("admin/forgot_password.html")

        session["reset_email"] = email
        flash("Reset code sent! Check your inbox.", "success")
        return redirect(url_for("auth.verify_reset_otp"))

    return render_template("admin/forgot_password.html")


@auth_bp.route("/admin/verify-reset-otp", methods=["GET", "POST"])
def verify_reset_otp():
    if "reset_email" not in session:
        return redirect(url_for("auth.forgot_password"))

    email = session["reset_email"]

    if request.method == "POST":
        entered = request.form.get("otp", "").strip()
        entered_hash = hash_otp(entered)
        now = datetime.now(timezone.utc)

        from db_neon import get_db_connection

        try:
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, attempts FROM otp_tokens
                        WHERE email=%s AND used=FALSE AND expires_at > %s
                        ORDER BY created_at DESC LIMIT 1
                        """,
                        (email, now),
                    )
                    row = cur.fetchone()

                    if not row:
                        flash("Code expired. Request a new one.", "danger")
                        session.pop("reset_email", None)
                        return redirect(url_for("auth.forgot_password"))

                    token_id, attempts = row

                    if attempts >= 5:
                        cur.execute("UPDATE otp_tokens SET used=TRUE WHERE id=%s", (token_id,))
                        conn.commit()
                        flash("Too many attempts. Request a new code.", "danger")
                        session.pop("reset_email", None)
                        return redirect(url_for("auth.forgot_password"))

                    cur.execute(
                        "SELECT id FROM otp_tokens WHERE id=%s AND code_hash=%s",
                        (token_id, entered_hash),
                    )
                    valid = cur.fetchone()

                    if valid:
                        cur.execute("UPDATE otp_tokens SET used=TRUE WHERE id=%s", (token_id,))
                        conn.commit()
                        session["reset_verified"] = True
                        return redirect(url_for("auth.set_new_password"))

                    cur.execute(
                        "UPDATE otp_tokens SET attempts=attempts+1 WHERE id=%s",
                        (token_id,),
                    )
                    conn.commit()
                    remaining = 4 - attempts
                    flash(f"Incorrect code. {remaining} attempt(s) remaining.", "danger")
        except Exception:
            flash("Database error. Please try again.", "danger")

    return render_template("admin/verify_reset_otp.html", email=email)


@auth_bp.route("/admin/set-new-password", methods=["GET", "POST"])
def set_new_password():
    if not session.get("reset_verified") or not session.get("reset_email"):
        return redirect(url_for("auth.forgot_password"))

    if request.method == "POST":
        password = request.form.get("password", "").strip()
        confirm = request.form.get("confirm", "").strip()

        if len(password) < 8:
            flash("Password must be at least 8 characters.", "danger")
            return render_template("admin/set_new_password.html")
        if password != confirm:
            flash("Passwords do not match.", "danger")
            return render_template("admin/set_new_password.html")

        hashed = hash_password(password)
        email = session["reset_email"]

        from db_neon import get_db_connection

        try:
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE admin_users
                        SET password_hash=%s, updated_at=NOW()
                        WHERE email=%s
                        """,
                        (hashed, email),
                    )
                conn.commit()
        except Exception:
            flash("Database error. Please try again.", "danger")
            return render_template("admin/set_new_password.html")

        delete_token()
        session.pop("reset_email", None)
        session.pop("reset_verified", None)
        flash("Password updated. Please log in again.", "success")
        return redirect(url_for("auth.login"))

    return render_template("admin/set_new_password.html")
