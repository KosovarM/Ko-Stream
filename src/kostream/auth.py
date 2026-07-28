"""Session-based authentication helpers."""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable, TypeVar

from flask import current_app, redirect, request, session, url_for

from kostream.i18n import _
from kostream.users import User, attempt_login, find_user_by_id, load_users

F = TypeVar("F", bound=Callable[..., Any])

LOGIN_ERRORS = {
    "invalid": "Invalid username or password.",
    "restricted": "This account is restricted. Contact the master user.",
    "restricted_lockout": (
        "Account restricted after too many failed login attempts. "
        "Contact the master user."
    ),
}


def current_user_id() -> str | None:
    raw = session.get("user_id")
    return str(raw).strip() if raw else None


def current_user() -> User | None:
    uid = current_user_id()
    if not uid:
        return None
    users_path = current_app.config.get("USERS_PATH")
    if not users_path:
        return None
    return find_user_by_id(load_users(users_path), uid)


def user_has_role(*roles: str) -> bool:
    """True when the session user has one of the given roles."""
    user = current_user()
    if user is None:
        return False
    allowed = {r.casefold() for r in roles}
    return user.role.casefold() in allowed


def authenticate(username: str, password: str, users_path) -> tuple[User | None, str]:
    """Return ``(user, error_code)``; error_code is empty on success."""
    return attempt_login(users_path, username, password)


def login_error_message(error_code: str) -> str:
    """Return a localized login error for the active request locale."""
    return _(LOGIN_ERRORS.get(error_code, LOGIN_ERRORS["invalid"]))


def role_required(*roles: str) -> Callable[[F], F]:
    allowed = {r.casefold() for r in roles}

    def decorator(view: F) -> F:
        @wraps(view)
        def wrapped(*args: Any, **kwargs: Any):
            user = current_user()
            if user is None:
                if request.path.startswith("/api/"):
                    return {"ok": False, "error": "Login required"}, 401
                return redirect(url_for("login", next=request.path))
            if user.role.casefold() not in allowed:
                if request.path.startswith("/api/") or request.is_json:
                    return {"ok": False, "error": "Forbidden"}, 403
                return redirect(url_for("home"))
            return view(*args, **kwargs)

        return wrapped  # type: ignore[return-value]

    return decorator
