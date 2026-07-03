import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

APP_DATA_DIR = Path(os.getenv("APPDATA", "")) / "ShreejiAutoService"
TOKEN_FILE = APP_DATA_DIR / "auth_token.json"
TOKEN_LIFETIME_HOURS = 720  # 30 days


def get_token_path():
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    return TOKEN_FILE


def save_token(email):
    token = secrets.token_hex(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires_at = (
        datetime.now(timezone.utc) + timedelta(hours=TOKEN_LIFETIME_HOURS)
    ).isoformat()
    data = {"token_hash": token_hash, "email": email, "expires_at": expires_at}
    get_token_path().write_text(json.dumps(data))
    return token


def load_token():
    path = get_token_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        expires_at = datetime.fromisoformat(data["expires_at"])
        if datetime.now(timezone.utc) > expires_at:
            path.unlink(missing_ok=True)
            return None
        return data
    except Exception:
        path.unlink(missing_ok=True)
        return None


def delete_token():
    path = get_token_path()
    if path.exists():
        path.unlink()


def is_authenticated():
    return load_token() is not None
