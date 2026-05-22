from dotenv import load_dotenv
load_dotenv()

import os

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


def create_app():
    app = Flask(__name__)

    # =========================
    # Secret Key
    # =========================
    app.secret_key = os.environ.get(
        "SECRET_KEY",
        "shreeji-auto-key-2025"
    )

    # =========================
    # PostgreSQL DATABASE URL
    # =========================
    database_url = os.environ.get("DATABASE_URL")

    if not database_url:
        raise ValueError(
            "DATABASE_URL environment variable is required for PostgreSQL connection"
        )

    # IMPORTANT FIX:
    # Remove accidental DATABASE_URL= prefix if present
    if database_url.startswith("DATABASE_URL="):
        database_url = database_url.replace(
            "DATABASE_URL=",
            "",
            1
        )

    app.config["DATABASE_URL"] = database_url

    # =========================
    # Upload Folder
    # =========================
    app.config["UPLOAD_FOLDER"] = "static/uploads"

    os.makedirs(
        app.config["UPLOAD_FOLDER"],
        exist_ok=True
    )

    # =========================
    # Initialize Database
    # =========================
    init_db_app(app)

    # =========================
    # Session Sync
    # =========================
    @app.before_request
    def sync_session_user():
        ensure_session_user()

    # =========================
    # Register Blueprints
    # =========================
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(customer_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(salary_bp)
    app.register_blueprint(att_bp)

    # =========================
    # Health Check Route
    # =========================
    @app.route("/health")
    def health_check():
        return jsonify({
            "status": "ok",
            "message": "Garage Management System Running"
        })

    return app


app = create_app()


if __name__ == "__main__":
    app.config["TEMPLATES_AUTO_RELOAD"] = True

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )