from functools import wraps

from flask import redirect, url_for

from services.auth_service import ensure_desktop_admin_session
from utils.auth_token import is_authenticated


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not is_authenticated():
            return redirect(url_for("auth.desktop_login"))
        ensure_desktop_admin_session()
        return f(*args, **kwargs)

    return decorated
