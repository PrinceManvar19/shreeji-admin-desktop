import glob
import os
import sqlite3
import shutil
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify

from models.db import init_app as init_db_app
from routes.admin_routes import admin_bp
from routes.admin_salary_routes import salary_bp
from routes.admin_attendance_routes import att_bp
from routes.auth_routes import auth_bp
from routes.customer_routes import customer_bp
from routes.main_routes import main_bp
from services.auth_service import ensure_session_user
from utils.helpers import log_action



# Use LOCALAPPDATA on Windows for persistent storage, fallback to project dir
BASE_DIR = os.path.join(os.getenv("LOCALAPPDATA") or os.path.dirname(os.path.abspath(__file__)), "GarageManagement")

os.makedirs(BASE_DIR, exist_ok=True)

DB_PATH = os.path.join(BASE_DIR, "garage.db")


def _default_data_dir(app):
    configured_db = os.environ.get("GARAGE_DATABASE", "").strip()
    if configured_db:
        return os.path.dirname(os.path.abspath(configured_db))

    return os.path.join(app.root_path, "data")


def _database_score(path):
    if not path or not os.path.exists(path) or os.path.getsize(path) <= 0:
        return -1

    connection = None
    try:
        connection = sqlite3.connect(path)
        cursor = connection.cursor()
        total = 0
        for table in ("customers", "bookings", "slots", "admins"):
            try:
                total += int(cursor.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            except sqlite3.Error:
                return -1
        return total
    except sqlite3.Error:
        return -1
    finally:
        if connection:
            connection.close()


def _best_database_source(app, target_db_path):
    candidates = []
    legacy_db_path = os.path.join(app.root_path, "garage.db")
    data_db_path = os.path.join(app.root_path, "data", "garage.db")

    for candidate in (legacy_db_path, data_db_path):
        if os.path.abspath(candidate) != os.path.abspath(target_db_path):
            candidates.append(candidate)

    candidates.extend(sorted(glob.glob(os.path.join(app.root_path, "backup", "*.db")), reverse=True))

    best_path = None
    best_score = -1
    for candidate in candidates:
        score = _database_score(candidate)
        if score > best_score:
            best_path = candidate
            best_score = score
    return best_path, best_score


def resolve_database_path(app):
    """Resolve the active SQLite path, honoring explicit configuration."""
    configured_db = os.environ.get("GARAGE_DATABASE", "").strip()
    if configured_db == ":memory:":
        return configured_db

    db_path = os.path.abspath(configured_db) if configured_db else DB_PATH
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    current_score = _database_score(db_path)
    best_source_path, best_source_score = _best_database_source(app, db_path)

    if best_source_path and best_source_score > current_score:
        try:
            shutil.copy2(best_source_path, db_path)
            log_action("DB RESTORE", f"From {os.path.basename(best_source_path)}")
        except OSError as error:
            log_action("DB RESTORE SKIPPED", str(error))
    return db_path


def perform_auto_backup(app):
    """Auto-backup garage.db to backup/ folder, keep last 5 backups."""
    db_path = app.config["DATABASE"]
    if not os.path.exists(db_path):
        return

    # Use centralized backup directory under BASE_DIR
    backup_dir = Path(BASE_DIR) / "backup"
    backup_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    backup_filename = f"garage_backup_{timestamp}.db"
    backup_path = backup_dir / backup_filename

    try:
        shutil.copy2(db_path, backup_path)

        backups = list(backup_dir.glob("garage_backup_*.db"))
        if len(backups) > 5:
            backups.sort(key=os.path.getctime)
            for old_backup in backups[:-5]:
                try:
                    old_backup.unlink()
                except OSError:
                    pass
        log_action("AUTO BACKUP", f"Created {backup_filename}")
    except OSError as error:
        log_action("BACKUP ERROR", str(error))


def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get("SECRET_KEY", "shreeji-auto-key-2025")
    app.config["DATABASE"] = resolve_database_path(app)

    init_db_app(app)

    perform_auto_backup(app)

    @app.before_request
    def sync_session_user():
        ensure_session_user()

    @app.route("/admin/backup-db")
    def manual_backup():
        """Create a manual backup of the database."""

        from flask import flash, redirect, url_for
        try:
            db_path = app.config["DATABASE"]
            if not os.path.exists(db_path):
                flash("Database not found", "error")
                return redirect(url_for("admin.admin"))

            # Create backup in the centralized backup directory
            backup_dir = Path(BASE_DIR) / "backup"
            backup_dir.mkdir(exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_filename = f"garage_backup_{timestamp}.db"
            backup_path = backup_dir / backup_filename

            shutil.copy2(db_path, backup_path)
            log_action("MANUAL BACKUP", f"Created {backup_filename}")

            flash(f"Backup created successfully: {backup_filename}", "success")
        except Exception as error:
            log_action("MANUAL BACKUP ERROR", str(error))
            flash(f"Backup failed: {str(error)}", "error")

        return redirect(url_for("admin.admin"))

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(customer_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(salary_bp)
    app.register_blueprint(att_bp)
    return app



app = create_app()


if __name__ == "__main__":
    app.config['TEMPLATES_AUTO_RELOAD'] = True
    app.run(host="0.0.0.0", port=5000, debug=True)
