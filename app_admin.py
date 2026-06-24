import os

from dotenv import load_dotenv
from flask import Flask, jsonify

import db_neon
from db_local import init_local_db
from routes.admin_attendance_routes import att_bp
from routes.admin_routes import admin_bp
from routes.admin_salary_routes import salary_bp
from routes.auth_routes import auth_bp
from routes.main_routes import main_bp
from services.auth_service import ensure_session_user


def is_railway_environment():
    return any(
        os.environ.get(name)
        for name in (
            "RAILWAY_ENVIRONMENT",
            "RAILWAY_ENVIRONMENT_NAME",
            "RAILWAY_PROJECT_ID",
            "RAILWAY_SERVICE_ID",
            "RAILWAY_STATIC_URL",
        )
    )


def load_environment():
    environment = "RAILWAY" if is_railway_environment() else "LOCAL"
    if environment == "LOCAL":
        load_dotenv(override=False)
    return environment


def clean_database_url(database_url):
    cleaned = (database_url or "").strip()
    if (
        len(cleaned) >= 2
        and cleaned[0] == cleaned[-1]
        and cleaned[0] in ("'", '"')
    ):
        cleaned = cleaned[1:-1].strip()

    if cleaned.startswith("DATABASE_URL="):
        cleaned = cleaned.replace("DATABASE_URL=", "", 1).strip()

    if (
        len(cleaned) >= 2
        and cleaned[0] == cleaned[-1]
        and cleaned[0] in ("'", '"')
    ):
        cleaned = cleaned[1:-1].strip()

    return cleaned


def database_url_error(database_url):
    if not database_url:
        return (
            "DATABASE_URL is missing. Add it to Railway Variables for the "
            "same service that runs gunicorn."
        )
    if not database_url.startswith(("postgresql://", "postgres://")):
        return (
            "DATABASE_URL must start with postgresql:// or postgres://. "
            "Do not include quotes or a DATABASE_URL= prefix in Railway."
        )
    return ""


def print_startup_diagnostics(environment, database_url):
    print("--------------------------------------------------", flush=True)
    print(f"Environment: {environment}", flush=True)
    print(f"DATABASE_URL Found: {'YES' if database_url else 'NO'}", flush=True)
    print(f"DATABASE_URL Length: {len(database_url or '')}", flush=True)
    print(f"Local SQLite path: {os.path.join('data', 'garage.db')}", flush=True)
    print("--------------------------------------------------", flush=True)


def register_configuration_error_routes(app, message):
    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def configuration_error(path):
        if path == "health":
            return jsonify({
                "status": "configuration_error",
                "message": message,
            }), 503

        return (
            "<h1>Garage Management configuration error</h1>"
            f"<p>{message}</p>"
            "<p>Set Railway Variables -> DATABASE_URL to the raw Neon "
            "PostgreSQL URL, then redeploy.</p>",
            503,
        )


def create_app():
    environment = load_environment()
    database_url = clean_database_url(os.environ.get("DATABASE_URL"))
    print_startup_diagnostics(environment, database_url)

    app = Flask(__name__)

    secret_key = os.environ.get("SECRET_KEY")
    if not secret_key:
        raise RuntimeError(
            "SECRET_KEY environment variable is not set. "
            "Set it in Railway environment variables or .env file before starting."
        )
    app.config["SECRET_KEY"] = secret_key
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = False
    app.config["SESSION_COOKIE_HTTPONLY"] = True

    app.config["UPLOAD_FOLDER"] = "static/uploads"
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    try:
        init_local_db()
        print("Local SQLite database initialised.", flush=True)
    except Exception as error:
        print(f"WARNING: Local SQLite init failed: {error}", flush=True)

    config_error = database_url_error(database_url)
    if config_error:
        print(f"STARTUP CONFIGURATION ERROR: {config_error}", flush=True)
        app.config["STARTUP_CONFIG_ERROR"] = config_error
        register_configuration_error_routes(app, config_error)
        return app

    app.config["DATABASE_URL"] = database_url

    db_neon.init_app(app)

    @app.before_request
    def sync_session_user():
        ensure_session_user()

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(salary_bp)
    app.register_blueprint(att_bp)

    @app.route("/health")
    def health_check():
        return jsonify({
            "status": "ok",
            "environment": environment,
            "database_url_found": True,
            "db_ready": db_neon.db_ready,
            "db_error": str(db_neon.db_error) if db_neon.db_error else "",
            "local_db": "initialised",
            "mode": "admin",
            "message": "Garage Management System Running",
        })

    return app


app = create_app()


if __name__ == "__main__":
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5050)),
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true",
    )
