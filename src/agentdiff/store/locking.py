from __future__ import annotations

import fcntl
import os
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from agentdiff.store.base import StoreError


@runtime_checkable
class FileLock(Protocol):
    """Advisory lock abstraction; backends are swappable per platform (A12)."""

    def __enter__(self) -> FileLock: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: Any,
    ) -> None: ...


class FlockFileLock:
    """POSIX backend: exclusive `fcntl.flock` on the lock path."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._fd: int | None = None

    def __enter__(self) -> FlockFileLock:
        self._fd = os.open(self._path, os.O_CREAT | os.O_RDWR)
        fcntl.flock(self._fd, fcntl.LOCK_EX)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: Any,
    ) -> None:
        if self._fd is None:
            return
        fcntl.flock(self._fd, fcntl.LOCK_UN)
        os.close(self._fd)
        self._fd = None


# WindowsFileLock (msvcrt.locking) is a LATER ISSUE, not built in this slice.
# Only the FileLock infra above plus the factory below is shipped now.

_POSIX = "posix"


def file_lock(path: Path) -> FileLock:
    """Return the platform's lock backend (A12).

    Only the POSIX backend exists yet; any other platform raises `StoreError`
    loudly rather than silently disabling mutual exclusion.
    """
    if os.name != _POSIX:
        raise StoreError(f"no file-lock backend for platform {os.name!r}")
    return FlockFileLock(path)
