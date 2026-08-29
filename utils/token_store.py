import json
import os
import secrets
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

APP_DATA_DIR = Path(os.getenv('APPDATA', '')) / 'ShreejiAutoService'
TOKEN_FILE = APP_DATA_DIR / 'auth_token.json'
TOKEN_LIFETIME_DAYS = 30

def _ensure_dir():
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)

def save_token(admin_id: str) -> None:
    _ensure_dir()
    token = secrets.token_hex(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires_at = (datetime.now(timezone.utc) +
                  timedelta(days=TOKEN_LIFETIME_DAYS)).isoformat()
    TOKEN_FILE.write_text(json.dumps({
        'token_hash': token_hash,
        'admin_id': admin_id,
        'expires_at': expires_at
    }))

def load_token() -> dict | None:
    if not TOKEN_FILE.exists():
        return None
    try:
        data = json.loads(TOKEN_FILE.read_text())
        expires_at = datetime.fromisoformat(data['expires_at'])
        if datetime.now(timezone.utc) > expires_at:
            TOKEN_FILE.unlink(missing_ok=True)
            return None
        return data
    except Exception:
        TOKEN_FILE.unlink(missing_ok=True)
        return None

def delete_token() -> None:
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()

def is_authenticated() -> bool:
    return load_token() is not None
