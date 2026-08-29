import os

from dotenv import load_dotenv
from flask import Flask, jsonify, request

import db_neon
from blueprints.auth import auth_bp
from db_local import init_local_db
from routes.admin_attendance_routes import att_bp
from routes.admin_routes import admin_bp
from routes.admin_salary_routes import salary_bp
from routes.auth_routes import auth_bp as public_auth_bp
from routes.main_routes import main_bp
from services.auth_service import ensure_session_user


def is_hosted_environment():
    """Detect if running on a hosted platform (Render, Railway, or similar).
    
    Checks for environment variables set by common hosting platforms.
    If any are present, assumes we're in a hosted/production environment.
    """
    return any(
        os.environ.get(name)
        for name in (
            # Render
            "RENDER",
            "RENDER_GIT_BRANCH",
            "RENDER_GIT_COMMIT",
            "RENDER_GIT_REPO_SLUG",
            "RENDER_INSTANCE_ID",
            "RENDER_SERVICE_ID",
            # Railway (legacy support)
            "RAILWAY_ENVIRONMENT",
            "RAILWAY_ENVIRONMENT_NAME",
            "RAILWAY_PROJECT_ID",
            "RAILWAY_SERVICE_ID",
            "RAILWAY_STATIC_URL",
        )
    )


def load_environment():
    environment = "HOSTED" if is_hosted_environment() else "LOCAL"
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
            "DATABASE_URL is missing. Set it in your hosting platform's "
            "environment variables (or in .env for local development)."
        )
    if not database_url.startswith(("postgresql://", "postgres://")):
        return (
            "DATABASE_URL must start with postgresql:// or postgres://. "
            "Do not include quotes or a DATABASE_URL= prefix."
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
            "<p>Set DATABASE_URL in your hosting platform environment variables "
            "(e.g., Render, Railway) or in .env for local development, "
            "then redeploy.</p>",
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
            "Set it in your hosting platform environment variables or .env file before starting."
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
        """
        Ensure session user is synchronized on every request.
        Wrapped with error logging for packaged build diagnostics.
        """
        import traceback
        import os
        from pathlib import Path
        import json
        from datetime import datetime
        
        log_file = Path(os.getcwd()) / "admin_login.log"
        try:
            ensure_session_user()
        except Exception as e:
            # Log before_request errors (includes page load crashes)
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "phase": "before_request",
                "request_path": str(request.path) if request else "unknown",
                "error": {
                    "type": type(e).__name__,
                    "message": str(e),
                    "traceback": traceback.format_exc(),
                }
            }
            try:
                with open(log_file, "a") as f:
                    f.write(json.dumps(log_entry) + "\n")
            except Exception:
                pass  # Ignore logging failures
            raise  # Re-raise so error propagates and shows 500 page

    app.register_blueprint(main_bp)
    app.register_blueprint(public_auth_bp)
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
