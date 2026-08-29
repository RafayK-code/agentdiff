from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from tests.diff.conftest import load_fixture

from agentdiff.diff.parse import parse_unified_diff
from agentdiff.model import Change, Comment, CommentState, LineRange, Side
from agentdiff.store import JsonlStore, create_store

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


@pytest.fixture
def change() -> Change:
    return parse_unified_diff(load_fixture("basic.patch"))


@pytest.fixture
def store(tmp_path: Path) -> JsonlStore:
    store = create_store(tmp_path)
    assert isinstance(store, JsonlStore)
    return store
