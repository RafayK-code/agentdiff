from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest
from tests.diff.conftest import load_fixture

from agentdiff.diff.parse import parse_unified_diff
from agentdiff.model import Change, Comment, CommentState, LineRange, Side
from agentdiff.store import JsonlStore, Store, create_store

_MISSING = object()
_DEFAULT_AT = datetime(2000, 1, 1, 12, 0, tzinfo=timezone.utc)


def comment_factory(
    change: Change,
    *,
    id: str = "c",
    change_id: str | None = None,
    file: str = "src/foo.py",
    range: LineRange | None = _MISSING,  # type: ignore[assignment]
    text: str = "t",
    author: str = "alice",
    state: CommentState = CommentState.ACTIVE,
    thread_id: str | None = None,
    created_at: datetime = _DEFAULT_AT,
    updated_at: datetime = _DEFAULT_AT,
) -> Comment:
    if range is _MISSING:
        range = LineRange(side=Side.NEW, start=1, end=1)
    return Comment(
        id=id,
        change_id=change_id if change_id is not None else change.id,
        file=file,
        range=range,
        text=text,
        author=author,
        state=state,
        thread_id=thread_id,
        created_at=created_at,
        updated_at=updated_at,
    )


def _parsed_basic() -> Change:
    return parse_unified_diff(load_fixture("basic.patch"))


@dataclass
class CanonicalStore:
    """The multi-branch chain store shared by the 05-cli store/CLI suites.

    Holds four changes parsed from ``basic.patch`` (file ``src/foo.py``) with
    forced ids/branches/revisions: ``chg-aaa`` + ``chg-bbb`` on ``feat/x``
    (linked, so ``chg-aaa`` is locked), ``chg-mmm`` on ``main``, and the
    patch import ``chg-ppp`` (``branch=None``). Comments ``c-1``/``c-2`` are
    added to ``chg-aaa`` while it is still the only feat/x change; the
    ``chg-bbb`` link (which locks it) comes last.
    """

    root: Path
    store: Store
    chg_aaa: Change
    chg_bbb: Change
    chg_mmm: Change
    chg_ppp: Change

    def change(self, change_id: str) -> Change:
        return {
            "chg-aaa": self.chg_aaa,
            "chg-bbb": self.chg_bbb,
            "chg-mmm": self.chg_mmm,
            "chg-ppp": self.chg_ppp,
        }[change_id]


def build_canonical_store(root: Path) -> CanonicalStore:
    """Build the canonical store at ``root`` (store factory + ``save_change``)."""
    base = _parsed_basic()
    chg_aaa = base.model_copy(
        update={
            "id": "chg-aaa",
            "branch": "feat/x",
            "prev_change": None,
            "base_revision": "3f2a1b0",
            "head_revision": "9c7d0e1",
        }
    )
    chg_bbb = base.model_copy(
        update={
            "id": "chg-bbb",
            "branch": "feat/x",
            "prev_change": "chg-aaa",
            "base_revision": "9c7d0e1",
            "head_revision": "d4e5f6a",
        }
    )
    chg_mmm = base.model_copy(
        update={
            "id": "chg-mmm",
            "branch": "main",
            "prev_change": None,
            "base_revision": "abcdef0",
            "head_revision": "1234567",
        }
    )
    chg_ppp = base.model_copy(
        update={
            "id": "chg-ppp",
            "branch": None,
            "prev_change": None,
            "base_revision": None,
            "head_revision": None,
        }
    )
    store = create_store(root)
    store.save_change(chg_aaa)
    store.add_comment(comment_factory(chg_aaa, id="c-1", state=CommentState.ACTIVE))
    store.add_comment(comment_factory(chg_aaa, id="c-2", state=CommentState.RESOLVED))
    store.save_change(chg_bbb)
    store.add_comment(comment_factory(chg_bbb, id="c-3", state=CommentState.ACTIVE))
    store.save_change(chg_mmm)
    store.add_comment(comment_factory(chg_mmm, id="c-m", state=CommentState.ACTIVE))
    store.save_change(chg_ppp)
    return CanonicalStore(
        root=root,
        store=store,
        chg_aaa=chg_aaa,
        chg_bbb=chg_bbb,
        chg_mmm=chg_mmm,
        chg_ppp=chg_ppp,
    )


@pytest.fixture
def canonical_store(tmp_path: Path) -> CanonicalStore:
    return build_canonical_store(tmp_path)


@pytest.fixture
def change() -> Change:
    return _parsed_basic()


@pytest.fixture
def store(tmp_path: Path) -> JsonlStore:
    store = create_store(tmp_path)
    assert isinstance(store, JsonlStore)
    return store
