from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for

from models.customer_model import create_customer, find_customer
from services.auth_service import login_user_by_identifier, set_user_session
from utils.helpers import log_action


auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
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
