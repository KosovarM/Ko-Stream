"""User account store."""

from __future__ import annotations

from pathlib import Path

import pytest

from kostream.users import (
    UsersError,
    MAX_FAILED_LOGIN_ATTEMPTS,
    attempt_login,
    bootstrap_master,
    create_user,
    load_users,
    reset_password,
    set_restricted,
    verify_password,
)


def test_create_user_and_verify_password(tmp_path: Path):
    path = tmp_path / "users.json"
    user = create_user(path, username="Alice", password="secret123", role="user")
    assert user.username == "Alice"
    assert user.role == "user"
    assert user.restricted is False
    assert user.failed_login_attempts == 0

    loaded = load_users(path)
    assert len(loaded) == 1
    assert verify_password(loaded[0], "secret123")
    assert not verify_password(loaded[0], "wrong")


def test_duplicate_username_rejected(tmp_path: Path):
    path = tmp_path / "users.json"
    create_user(path, username="bob", password="pass1")
    with pytest.raises(UsersError, match="already taken"):
        create_user(path, username="Bob", password="pass2")


def test_single_master_enforced(tmp_path: Path):
    path = tmp_path / "users.json"
    bootstrap_master(path, "admin", "adminpass")
    with pytest.raises(UsersError, match="master"):
        create_user(path, username="other", password="x", role="master")


def test_bootstrap_master_creates_master(tmp_path: Path):
    path = tmp_path / "users.json"
    user = bootstrap_master(path, "kosovar", "pw")
    assert user.role == "master"
    assert user.id == "u_kosovar"


def test_set_restricted_manual(tmp_path: Path):
    path = tmp_path / "users.json"
    user = create_user(path, username="bob", password="pass1")
    updated = set_restricted(path, user.id, restricted=True)
    assert updated.restricted is True
    restored = set_restricted(path, user.id, restricted=False)
    assert restored.restricted is False
    assert restored.failed_login_attempts == 0


def test_auto_restrict_after_failed_logins(tmp_path: Path):
    path = tmp_path / "users.json"
    create_user(path, username="bob", password="pass1")
    for _ in range(MAX_FAILED_LOGIN_ATTEMPTS - 1):
        user, code = attempt_login(path, "bob", "wrong")
        assert user is None
        assert code == "invalid"
    user, code = attempt_login(path, "bob", "wrong")
    assert user is None
    assert code == "restricted_lockout"
    loaded = load_users(path)[0]
    assert loaded.restricted is True
    assert loaded.failed_login_attempts == MAX_FAILED_LOGIN_ATTEMPTS


def test_successful_login_resets_failed_attempts(tmp_path: Path):
    path = tmp_path / "users.json"
    create_user(path, username="bob", password="pass1")
    attempt_login(path, "bob", "wrong")
    user, code = attempt_login(path, "bob", "pass1")
    assert code == ""
    assert user is not None
    assert load_users(path)[0].failed_login_attempts == 0


def test_reset_password(tmp_path: Path):
    path = tmp_path / "users.json"
    user = create_user(path, username="bob", password="oldpass")
    reset_password(path, user.id, "newpass")
    loaded = load_users(path)[0]
    assert verify_password(loaded, "newpass")
    assert not verify_password(loaded, "oldpass")
