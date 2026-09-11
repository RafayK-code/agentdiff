from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest
from tests.diff.conftest import load_fixture

from agentdiff.diff.parse import parse_unified_diff
from agentdiff.model import (
    Change,
    Comment,
    CommentState,
    LineRange,
    Side,
    Version,
)
from agentdiff.store import JsonlStore, Store, create_store

_MISSING = object()
_DEFAULT_AT = datetime(2000, 1, 1, 12, 0, tzinfo=timezone.utc)


def comment_factory(
    change: Change,
    *,
    id: str = "c",
    change_id: str | None = None,
    revision: str | None = None,
    file: str = "src/foo.py",
    range: LineRange | None = _MISSING,  # type: ignore[assignment]
    text: str = "t",
    author: str = "alice",
    state: CommentState = CommentState.ACTIVE,
    drifted: bool = False,
    in_reply_to: str | None = None,
    anchor_snapshot: list[str] | None = None,
    created_at: datetime = _DEFAULT_AT,
    updated_at: datetime = _DEFAULT_AT,
) -> Comment:
    if range is _MISSING:
        range = LineRange(side=Side.NEW, start=1, end=1)
    if revision is None:
        revision = change.head_revision or ""
    return Comment(
        id=id,
        change_id=change_id if change_id is not None else change.id,
        revision=revision,
        file=file,
        range=range,
        text=text,
        author=author,
        state=state,
        drifted=drifted,
        in_reply_to=in_reply_to,
        anchor_snapshot=anchor_snapshot or [],
        created_at=created_at,
        updated_at=updated_at,
    )


def _parsed_basic() -> Change:
    return parse_unified_diff(load_fixture("basic.patch"))


def _version(revision: str, created_at: datetime | None = None) -> Version:
    return Version(
        revision=revision, files=_parsed_basic().files, created_at=created_at
    )


@dataclass
class CanonicalStore:
    """The multi-branch version store shared by the store/CLI suites.

    Holds four changes parsed from ``basic.patch`` (file ``src/foo.py``) with
    forced ids/branches/revisions: ``chg-aaa`` and ``chg-bbb`` on ``feat/x``
    (``chg-bbb`` has the later current version), ``chg-mmm`` on ``main``, and
    the patch import ``chg-ppp`` (``branch=None``).
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
    early = datetime(2024, 1, 1, tzinfo=timezone.utc)
    late = datetime(2024, 6, 1, tzinfo=timezone.utc)
    chg_aaa = Change(
        id="chg-aaa",
        branch="feat/x",
        base_revision="3f2a1b0",
        versions=[_version("9c7d0e1", early)],
        created_at=early,
    )
    chg_bbb = Change(
        id="chg-bbb",
        branch="feat/x",
        base_revision="9c7d0e1",
        versions=[_version("d4e5f6a", late)],
        created_at=late,
    )
    chg_mmm = Change(
        id="chg-mmm",
        branch="main",
        base_revision="abcdef0",
        versions=[_version("1234567", early)],
        created_at=early,
    )
    chg_ppp = Change(
        id="chg-ppp",
        branch=None,
        base_revision=None,
        versions=[_version("ppp0001")],
    )
    store = create_store(root)
    store.save_change(chg_aaa)
    store.add_comment(
        comment_factory(
            chg_aaa, id="c-1", revision="9c7d0e1", state=CommentState.ACTIVE
        )
    )
    store.add_comment(
        comment_factory(
            chg_aaa, id="c-2", revision="9c7d0e1", state=CommentState.RESOLVED
        )
    )
    store.save_change(chg_bbb)
    store.add_comment(
        comment_factory(
            chg_bbb, id="c-3", revision="d4e5f6a", state=CommentState.ACTIVE
        )
    )
    store.add_comment(
        comment_factory(
            chg_bbb, id="c-4", revision="d4e5f6a", state=CommentState.CLOSED
        )
    )
    store.save_change(chg_mmm)
    store.add_comment(
        comment_factory(
            chg_mmm, id="c-m", revision="1234567", state=CommentState.ACTIVE
        )
    )
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
