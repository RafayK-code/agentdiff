from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from pathlib import Path

from agentdiff.store.base import Store, StoreError
from agentdiff.store.jsonl import JsonlStore


class StoreBackend(str, Enum):
    """Known store backends (A13). Adding a backend = one registry entry."""

    JSONL = "jsonl"
    # SQLITE = "sqlite"   # LATER backend; not in this slice


_BACKENDS: dict[StoreBackend, Callable[[Path | str], Store]] = {
    StoreBackend.JSONL: JsonlStore,
}


def create_store(
    root: Path | str, *, backend: StoreBackend | str = StoreBackend.JSONL
) -> Store:
    """Return the requested store backend (A13).

    Callers never construct a store directly, so the creation API stays stable
    when a sqlite backend lands. Unknown backends raise a typed ``StoreError``
    (never ``KeyError``); the message names the requested backend.
    """
    try:
        backend = StoreBackend(backend)
    except ValueError as exc:
        raise StoreError(f"unknown store backend {backend!r}") from exc
    try:
        store_cls = _BACKENDS[backend]
    except KeyError as exc:
        raise StoreError(f"no store implementation for {backend.value!r}") from exc
    return store_cls(root)
