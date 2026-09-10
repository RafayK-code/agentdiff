from __future__ import annotations

import io
from pathlib import Path

import pytest
from tests.store.conftest import CanonicalStore, build_canonical_store

from agentdiff.store import create_store


class FakeTTY(io.StringIO):
    """A StringIO that reports itself as a TTY, for the bare-command test."""

    def isatty(self) -> bool:
        return True


@pytest.fixture
def store_root(tmp_path: Path) -> Path:
    return tmp_path / "store"


@pytest.fixture
def canonical_store(store_root: Path) -> CanonicalStore:
    return build_canonical_store(store_root)


@pytest.fixture
def decoy_root(tmp_path: Path) -> Path:
    root = tmp_path / "decoy"
    store = create_store(root)
    base = build_canonical_store(tmp_path / "seed").chg_aaa
    store.save_change(base.model_copy(update={"id": "chg-zzz", "branch": "decoy"}))
    return root
