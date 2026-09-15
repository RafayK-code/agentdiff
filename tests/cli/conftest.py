from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from tests.store.conftest import CanonicalStore, build_canonical_store
from tests.tui.conftest import comment_factory, make_version

from agentdiff.model import Change, CommentState, LineRange, Role, Side
from agentdiff.store import Store, create_store

NOW = datetime(2020, 1, 1, tzinfo=timezone.utc)


def later(seconds: int) -> datetime:
    return NOW + timedelta(seconds=seconds)


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
def convo_store_root(tmp_path: Path) -> Path:
    return tmp_path / "convo"


@pytest.fixture
def convo_store(convo_store_root: Path) -> Store:
    """A change with three threads: agent-last, human-last, and resolved."""
    store = create_store(convo_store_root)
    store.save_change(
        Change(id="chg-s", versions=[make_version("rev-1", "basic.patch")])
    )
    for root_id, reply_id, reply_role, reply_state, line in (
        ("c-a", "c-a2", Role.AGENT, CommentState.ACTIVE, 1),
        ("c-b", "c-b2", Role.HUMAN, CommentState.ACTIVE, 2),
        ("c-c", "c-c2", Role.AGENT, CommentState.RESOLVED, 3),
    ):
        store.add_comment(
            comment_factory(
                root_id,
                change_id="chg-s",
                revision="rev-1",
                role=Role.HUMAN,
                range=LineRange(side=Side.NEW, start=line, end=line),
                created_at=NOW,
            )
        )
        store.add_comment(
            comment_factory(
                reply_id,
                change_id="chg-s",
                revision="rev-1",
                role=reply_role,
                state=reply_state,
                in_reply_to=root_id,
                range=LineRange(side=Side.NEW, start=line, end=line),
                created_at=later(1),
            )
        )
    return store


@pytest.fixture
def decoy_root(tmp_path: Path) -> Path:
    root = tmp_path / "decoy"
    store = create_store(root)
    base = build_canonical_store(tmp_path / "seed").chg_aaa
    store.save_change(base.model_copy(update={"id": "chg-zzz", "branch": "decoy"}))
    return root
