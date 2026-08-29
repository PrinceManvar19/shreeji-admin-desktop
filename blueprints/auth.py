from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from utils.auth_helpers import hash_password, verify_password
from utils.token_store import delete_token, is_authenticated, save_token


auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/admin/login", methods=["GET", "POST"])
def login():
    if is_authenticated():
        return redirect(url_for("admin.admin"))

    if request.method == "POST":
        admin_id = request.form.get("admin_id", "").strip().upper()
        password = request.form.get("password", "").strip()

        from db_neon import get_db_connection

        try:
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, name, phone, password_hash FROM admins WHERE id = %s",
                        (admin_id,),
                    )
                    row = cur.fetchone()
        except Exception:
            flash("Database error. Check internet connection.", "danger")
            return render_template("admin/login.html")

        if not row:
            flash("Invalid admin ID or password.", "danger")
            return render_template("admin/login.html")

        admin_record = dict(row)
        password_hash = admin_record.get("password_hash")

        if not password_hash or not verify_password(password, password_hash):
            flash("Invalid admin ID or password.", "danger")
            return render_template("admin/login.html")

        save_token(admin_id)
        session.clear()
        session["admin_logged_in"] = True
        session["admin_id"] = admin_id
        session["admin_name"] = admin_record.get("name", "Admin")
        return redirect(url_for("admin.admin"))

    return render_template("admin/login.html")


@auth_bp.route("/admin/logout")
def logout():
    delete_token()
    session.clear()
    return redirect(url_for("auth.login"))


# Compatibility redirects for existing admin guards/templates.
@auth_bp.route("/desktop/login", endpoint="desktop_login")
def desktop_login_redirect():
    return redirect(url_for("auth.login"))


@auth_bp.route("/desktop/logout", endpoint="desktop_logout")
def desktop_logout_redirect():
    return logout()
