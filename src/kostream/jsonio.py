"""Atomic JSON writes with a light advisory file lock.

Used by concurrent JSON stores (catalog, progress, users, sync index, etc.)
so a crash mid-write does not leave a truncated file, and two threads/processes
are less likely to clobber each other.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


def atomic_write_json(
    path: Path | str,
    data: Any,
    *,
    indent: int | None = 2,
    ensure_ascii: bool = False,
    trailing_newline: bool = True,
) -> None:
    """Serialize ``data`` to JSON and replace ``path`` atomically."""
    target = Path(path)
    text = json.dumps(data, indent=indent, ensure_ascii=ensure_ascii)
    if trailing_newline:
        text += "\n"
    atomic_write_text(target, text)


def atomic_write_text(path: Path | str, text: str) -> None:
    """Write ``text`` via temp file + ``os.replace``, under an advisory lock."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = text if isinstance(text, str) else str(text)
    with _advisory_lock(target):
        fd, tmp_name = tempfile.mkstemp(
            dir=str(target.parent),
            prefix=f".{target.name}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, target)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise


@contextmanager
def _advisory_lock(target: Path) -> Iterator[None]:
    """Best-effort cross-process lock via a sidecar ``.lock`` file."""
    lock_path = target.with_name(target.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    # Binary mode required for msvcrt.locking on Windows.
    with open(lock_path, "a+b") as lock_file:
        _lock_acquire(lock_file)
        try:
            yield
        finally:
            _lock_release(lock_file)


def _lock_acquire(lock_file: Any, *, timeout_s: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_s
    if sys.platform == "win32":
        import msvcrt

        while True:
            try:
                lock_file.seek(0)
                if lock_file.read(1) == b"":
                    lock_file.write(b"\0")
                    lock_file.flush()
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Timed out locking {lock_file.name}")
                time.sleep(0.02)
    else:
        import fcntl

        while True:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Timed out locking {lock_file.name}")
                time.sleep(0.02)


def _lock_release(lock_file: Any) -> None:
    try:
        if sys.platform == "win32":
            import msvcrt

            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
