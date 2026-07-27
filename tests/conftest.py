"""Shared pytest fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _disable_csrf_by_default(monkeypatch):
    """Keep existing API tests simple; CSRF is covered in test_csrf.py."""
    monkeypatch.setenv("KOSTREAM_CSRF", "0")
