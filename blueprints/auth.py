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
        from psycopg2.extras import RealDictCursor
        import traceback
        import os
        from pathlib import Path
        import json
        from datetime import datetime

        # Log all login attempts for debugging packaged builds
        log_file = Path(os.getcwd()) / "admin_login.log"
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "admin_id": admin_id,
            "status": "unknown",
            "error": None,
        }

        try:
            with get_db_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        "SELECT id, name, phone, password_hash FROM admins WHERE id = %s",
                        (admin_id,),
                    )
                    row = cur.fetchone()
            log_entry["status"] = "query_success"
        except Exception as e:
            log_entry["status"] = "query_failed"
            log_entry["error"] = {
                "type": type(e).__name__,
                "message": str(e),
                "traceback": traceback.format_exc(),
            }
            with open(log_file, "a") as f:
                f.write(json.dumps(log_entry) + "\n")
            flash("Database error. Check internet connection.", "danger")
            return render_template("admin/login.html")

        if not row:
            log_entry["status"] = "invalid_credentials"
            with open(log_file, "a") as f:
                f.write(json.dumps(log_entry) + "\n")
            flash("Invalid admin ID or password.", "danger")
            return render_template("admin/login.html")

        try:
            admin_record = dict(row)
            password_hash = admin_record.get("password_hash")

            if not password_hash or not verify_password(password, password_hash):
                log_entry["status"] = "invalid_password"
                with open(log_file, "a") as f:
                    f.write(json.dumps(log_entry) + "\n")
                flash("Invalid admin ID or password.", "danger")
                return render_template("admin/login.html")

            save_token(admin_id)
            session.clear()
            session["admin_id"] = admin_id
            session["admin_name"] = admin_record.get("name", "Admin")
            
            log_entry["status"] = "login_success"
            with open(log_file, "a") as f:
                f.write(json.dumps(log_entry) + "\n")
            
            return redirect(url_for("admin.admin"))
        except Exception as e:
            log_entry["status"] = "post_query_failed"
            log_entry["error"] = {
                "type": type(e).__name__,
                "message": str(e),
                "traceback": traceback.format_exc(),
            }
            with open(log_file, "a") as f:
                f.write(json.dumps(log_entry) + "\n")
            flash("Login error. Please try again.", "danger")
            return render_template("admin/login.html")

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
