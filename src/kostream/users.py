"""Local user accounts stored in users.json."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from werkzeug.security import check_password_hash, generate_password_hash

from kostream.jsonio import atomic_write_json

USERS_FILE = Path(__file__).resolve().parents[2] / "data" / "users.json"

VALID_ROLES = frozenset({"master", "manager", "user"})
MAX_FAILED_LOGIN_ATTEMPTS = 3


class UsersError(Exception):
    """User account operation failed."""


ONLINE_WINDOW_SECONDS = 15 * 60


@dataclass
class User:
    id: str
    username: str
    password_hash: str
    role: str
    display_name: str
    created_at: str
    restricted: bool = False
    failed_login_attempts: int = 0
    last_seen: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "id": self.id,
            "username": self.username,
            "password_hash": self.password_hash,
            "role": self.role,
            "display_name": self.display_name,
            "created_at": self.created_at,
            "restricted": self.restricted,
            "failed_login_attempts": self.failed_login_attempts,
        }
        if self.last_seen:
            payload["last_seen"] = self.last_seen
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> User:
        return cls(
            id=str(data["id"]),
            username=str(data["username"]),
            password_hash=str(data["password_hash"]),
            role=str(data["role"]),
            display_name=str(data.get("display_name") or data["username"]),
            created_at=str(data.get("created_at") or ""),
            restricted=bool(data.get("restricted", data.get("disabled", False))),
            failed_login_attempts=int(data.get("failed_login_attempts", 0)),
            last_seen=(str(data["last_seen"]) if data.get("last_seen") else None),
        )

    def is_online(self, *, now: datetime | None = None, window_s: int = ONLINE_WINDOW_SECONDS) -> bool:
        if not self.last_seen:
            return False
        try:
            raw = self.last_seen.replace("Z", "+00:00")
            seen = datetime.fromisoformat(raw)
            if seen.tzinfo is None:
                seen = seen.replace(tzinfo=timezone.utc)
        except ValueError:
            return False
        current = now or datetime.now(timezone.utc)
        return (current - seen).total_seconds() <= window_s


def _user_id(username: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "", username.casefold())
    if not slug:
        raise UsersError("Username must contain at least one letter or digit")
    return f"u_{slug}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(user: User, password: str) -> bool:
    return check_password_hash(user.password_hash, password)


def load_users(path: Path | None = None) -> list[User]:
    target = path or USERS_FILE
    if not target.is_file():
        return []
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = raw.get("users") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        return []
    users: list[User] = []
    for item in items:
        if isinstance(item, dict) and item.get("id") and item.get("username"):
            users.append(User.from_dict(item))
    return users


def save_users(users: list[User], path: Path | None = None) -> None:
    target = path or USERS_FILE
    payload = {"users": [u.to_dict() for u in users]}
    atomic_write_json(target, payload)


def find_user_by_username(users: list[User], username: str) -> User | None:
    needle = username.casefold()
    for user in users:
        if user.username.casefold() == needle:
            return user
    return None


def find_user_by_id(users: list[User], user_id: str) -> User | None:
    for user in users:
        if user.id == user_id:
            return user
    return None


def users_bootstrapped(path: Path | None = None) -> bool:
    return len(load_users(path)) > 0


def _ensure_single_master(users: list[User], role: str) -> None:
    if role == "master" and any(u.role == "master" for u in users):
        raise UsersError("A master account already exists")


def create_user(
    path: Path,
    *,
    username: str,
    password: str,
    role: str = "user",
    display_name: str | None = None,
) -> User:
    username = username.strip()
    if not username:
        raise UsersError("Username is required")
    if not password:
        raise UsersError("Password is required")
    role = role.strip().casefold()
    if role not in VALID_ROLES:
        raise UsersError(f"Invalid role: {role}")

    users = load_users(path)
    if find_user_by_username(users, username):
        raise UsersError(f"Username already taken: {username}")
    _ensure_single_master(users, role)

    user = User(
        id=_user_id(username),
        username=username,
        password_hash=hash_password(password),
        role=role,
        display_name=(display_name or username).strip() or username,
        created_at=_now_iso(),
        restricted=False,
        failed_login_attempts=0,
    )
    users.append(user)
    save_users(users, path)
    return user


def bootstrap_master(path: Path, username: str, password: str) -> User:
    """Create the initial master account."""
    return create_user(path, username=username, password=password, role="master")


def _replace_user(users: list[User], updated: User) -> None:
    for index, user in enumerate(users):
        if user.id == updated.id:
            users[index] = updated
            return


def set_restricted(path: Path, user_id: str, *, restricted: bool) -> User:
    """Manually restrict or restore a user account."""
    users = load_users(path)
    user = find_user_by_id(users, user_id)
    if user is None:
        raise UsersError(f"Unknown user: {user_id}")
    user.restricted = restricted
    if not restricted:
        user.failed_login_attempts = 0
    _replace_user(users, user)
    save_users(users, path)
    return user


def reset_password(path: Path, user_id: str, new_password: str) -> User:
    """Set a new password hash for an existing user."""
    if not new_password:
        raise UsersError("Password is required")
    users = load_users(path)
    user = find_user_by_id(users, user_id)
    if user is None:
        raise UsersError(f"Unknown user: {user_id}")
    user.password_hash = hash_password(new_password)
    _replace_user(users, user)
    save_users(users, path)
    return user


def touch_last_seen(
    path: Path,
    user_id: str,
    *,
    min_interval_s: int = 60,
) -> User | None:
    """Update ``last_seen`` for activity / online indicator. Returns user or None.

    Skips rewrite when last touch was within ``min_interval_s`` to limit JSON churn.
    """
    users = load_users(path)
    user = find_user_by_id(users, user_id)
    if user is None:
        return None
    now = datetime.now(timezone.utc)
    if user.last_seen and min_interval_s > 0:
        try:
            raw = user.last_seen.replace("Z", "+00:00")
            seen = datetime.fromisoformat(raw)
            if seen.tzinfo is None:
                seen = seen.replace(tzinfo=timezone.utc)
            if (now - seen).total_seconds() < min_interval_s:
                return user
        except ValueError:
            pass
    user.last_seen = _now_iso()
    _replace_user(users, user)
    save_users(users, path)
    return user


def delete_user(path: Path, user_id: str) -> User:
    """Remove a non-master user account from users.json."""
    users = load_users(path)
    user = find_user_by_id(users, user_id)
    if user is None:
        raise UsersError(f"Unknown user: {user_id}")
    if user.role == "master":
        raise UsersError("Cannot delete the master account")
    save_users([u for u in users if u.id != user_id], path)
    return user


def attempt_login(path: Path, username: str, password: str) -> tuple[User | None, str]:
    """Authenticate and update failed-login counters.

    Returns ``(user, error_code)`` where ``error_code`` is one of:
    ``""`` (success), ``"invalid"``, ``"restricted"``, ``"restricted_lockout"``.
    """
    users = load_users(path)
    user = find_user_by_username(users, username)
    if user is None:
        return None, "invalid"
    if user.restricted:
        return None, "restricted"
    if verify_password(user, password):
        user.failed_login_attempts = 0
        _replace_user(users, user)
        save_users(users, path)
        return user, ""
    user.failed_login_attempts += 1
    if user.failed_login_attempts >= MAX_FAILED_LOGIN_ATTEMPTS:
        user.restricted = True
        _replace_user(users, user)
        save_users(users, path)
        return None, "restricted_lockout"
    _replace_user(users, user)
    save_users(users, path)
    return None, "invalid"
