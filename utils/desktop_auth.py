from functools import wraps

from flask import redirect, url_for

from utils.token_store import is_authenticated


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not is_authenticated():
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)

    return decorated
