import os

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for

from models.customer_model import create_customer, find_customer
from services.admin_otp_service import clear_admin_otp, pending_admin_otp_user, start_admin_otp, verify_admin_otp
from services.auth_service import ensure_desktop_admin_session, login_user_by_identifier, set_user_session
from utils.auth_token import delete_token, is_authenticated, save_token
from utils.helpers import log_action


auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    # Admin email OTP is temporarily disabled for now.
    session.pop("admin_otp", None)

    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip()
        try:
            user = login_user_by_identifier(identifier)
            if user:
                session.clear()
                set_user_session(user["id"], user["name"], user["role"], user.get("phone", ""))
                flash("Login successful!", "success")

                if user["role"] == "admin":
                    if "admin.admin" not in current_app.view_functions:
                        session.clear()
                        return redirect(url_for("auth.admin_info"))
                    return redirect(url_for("admin.admin"))
                return redirect(url_for("customer.dashboard"))

        except Exception as error:
            log_action("LOGIN ROUTE ERROR", f"{identifier}: {str(error)}")

        flash("Invalid credentials. Please check and try again.", "error")

    return render_template("login.html")


@auth_bp.route("/admin-info")
def admin_info():
    return render_template("admin_info.html")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        try:
            success, message, _customer = create_customer(
                request.form.get("name", ""),
                request.form.get("phone", ""),
                request.form.get("vehicle", ""),
            )
        except Exception as error:
            log_action("REGISTRATION ROUTE ERROR", str(error))
            flash("Registration failed. Please try again.", "error")
            return redirect(url_for("auth.register"))

        if not success:
            flash(message, "error")
            return redirect(url_for("auth.register"))
        flash("Registration successful. Please login.", "success")
        return redirect(url_for("auth.login"))
    return render_template("register.html")


@auth_bp.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully", "success")
    return redirect(url_for("main.home"))


@auth_bp.route("/desktop/login", methods=["GET", "POST"])
def desktop_login():
    if is_authenticated() and ensure_desktop_admin_session():
        return redirect(url_for("admin.admin"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        admin_email = (
            os.environ.get("ADMIN_EMAIL", "").strip().lower()
            or os.environ.get("ADMIN_OTP_EMAIL", "").strip().lower()
        )

        if not admin_email:
            flash("Admin OTP email is not configured.", "error")
            return render_template("login.html", desktop_auth=True)

        if email != admin_email:
            flash("If this email is registered, an OTP has been sent.", "info")
            return render_template("login.html", desktop_auth=True)

        user = {
            "id": os.getenv("ADMIN_DESKTOP_ID", "ADMIN001").strip().upper() or "ADMIN001",
            "name": "Owner",
            "phone": "",
            "role": "admin",
        }
        ok, message, _masked_email = start_admin_otp(user)
        if not ok:
            flash(message, "error")
            return render_template("login.html", desktop_auth=True)

        session["desktop_otp_email"] = email
        flash("OTP sent! Check your inbox.", "success")
        return redirect(url_for("auth.desktop_verify_otp"))

    return render_template("login.html", desktop_auth=True)


@auth_bp.route("/desktop/verify-otp", methods=["GET", "POST"])
def desktop_verify_otp():
    if not session.get("desktop_otp_email") or not pending_admin_otp_user():
        clear_admin_otp()
        session.pop("desktop_otp_email", None)
        return redirect(url_for("auth.desktop_login"))

    email = session["desktop_otp_email"]

    if request.method == "POST":
        ok, message, user = verify_admin_otp(request.form.get("otp", ""))
        if ok and user:
            session.clear()
            save_token(email)
            set_user_session(user["id"], user["name"], "admin", user.get("phone", ""))
            session["desktop_auth_email"] = email
            return redirect(url_for("admin.admin"))

        flash(message, "error")

    return render_template("verify_otp.html", email=email)


@auth_bp.route("/desktop/logout")
def desktop_logout():
    delete_token()
    session.clear()
    return redirect(url_for("auth.desktop_login"))


@auth_bp.route("/find-id", methods=["GET", "POST"])
def find_id():
    if request.method == "POST":
        match = find_customer(
            request.form.get("name", "").strip(),
            request.form.get("phone", "").strip(),
            request.form.get("vehicle", "").strip().upper(),
        )
        if match:
            flash(f'Your Customer ID: {match["id"]}', "success")
        else:
            flash("No match found. Visit service center.", "error")
        session["show_find_id_toast"] = True
        return redirect(url_for("auth.find_id"))

    toast = session.pop("show_find_id_toast", False)
    return render_template("find_id.html", toast=toast)
