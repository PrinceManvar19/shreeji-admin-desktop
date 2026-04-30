# Deployment Checklist — Shreeji Auto Garage

## Before first deploy

### 1. Set required environment variables
On your hosting platform (Render / Railway / Heroku), add these secrets:

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | **YES** | Long random string. Generate: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `GARAGE_DATABASE` | Recommended | Absolute path on persistent disk, e.g. `/var/data/garage.db` |
| `DATA_DIR` | Recommended | Base dir for backups/logs, e.g. `/var/data` |
| `FLASK_DEBUG` | NO | Leave unset (defaults to `0`). Never set to `1` in production. |

### 2. Remove committed database files from git history
The `.db` files were previously committed. Clean them:
```bash
git rm --cached "*.db" "**/*.db"
git commit -m "remove committed database files"
# To scrub full history (optional but recommended):
pip install git-filter-repo
git filter-repo --path-glob '*.db' --invert-paths
git push --force
```

### 3. Change the default admin PIN
After first deploy, log in as ADMIN001 with PIN `1234` (the seeded default).
**Immediately change the PIN** using the admin panel or via the Python shell:
```python
from models.admin_model import set_admin_pin
set_admin_pin("ADMIN001", "your-new-secure-pin")
set_admin_pin("ADMIN002", "your-new-secure-pin")
```

### 4. Persistent storage
SQLite needs a persistent disk. On Render: add a Disk to your service and set
`GARAGE_DATABASE` and `DATA_DIR` to point at it.

---

## What was fixed in this patch

| # | Issue | Fix |
|---|---|---|
| 1 | Hardcoded `SECRET_KEY` fallback | Raises `ValueError` at startup if not set |
| 2 | No CSRF protection | `Flask-WTF` `CSRFProtect` added; all POST forms patched |
| 3 | `/admin/backup-db` unauthenticated | Moved into `admin_bp` with `@require_admin` decorator |
| 4 | Admin login had no password | bcrypt-hashed PIN added to `admins` table |
| 5 | No rate limiting on login | 10 attempts / 60 s per IP; blocks further attempts |
| 6 | `LOCALAPPDATA` Windows-only path | Replaced with `DATA_DIR` env var + project-dir fallback |
| 7 | No 404 / 500 error handlers | `@app.errorhandler(404/500)` + template stubs added |
| 8 | `gunicorn` missing from requirements | Added `gunicorn==23.0.0` |
| 9 | `python-dotenv` never loaded | `load_dotenv()` called at top of `app.py` |
| 10 | Unused packages inflating requirements | Removed: SQLAlchemy, mysql-connector, Pillow, protobuf, Pygments, colorama |
| 11 | `debug=True` hardcoded | Now driven by `FLASK_DEBUG` env var |
| 12 | Copy-pasted auth guards | `@require_admin` and `@require_customer` decorators in `utils/helpers.py` |
| 13 | Public `/api/vehicles/<id>` enumeration risk | Now requires customer login; only returns own vehicles |
| 14 | DB files committed to repo | `.gitignore` updated; DB files excluded |
