"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from kostream.users import bootstrap_master, create_user


@pytest.fixture(autouse=True)
def _disable_csrf_by_default(monkeypatch):
    """Keep existing API tests simple; CSRF is covered in test_csrf.py."""
    monkeypatch.setenv("KOSTREAM_CSRF", "0")


def bootstrap_test_users(
    path: Path,
    username: str = "testuser",
    password: str = "testpass",
) -> None:
    """Create a master test account in the given users.json path."""
    bootstrap_master(path, username, password)


def add_test_user(
    path: Path,
    username: str,
    password: str,
    *,
    role: str = "user",
) -> None:
    create_user(path, username=username, password=password, role=role)


def login_client(client, username: str = "testuser", password: str = "testpass"):
    """POST /login and return the response (expects redirect on success)."""
    return client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )


def test_user_data_dir(tmp_path: Path) -> Path:
    """Isolated per-user progress directory for tests."""
    path = tmp_path / "user_data"
    path.mkdir(parents=True, exist_ok=True)
    return path
