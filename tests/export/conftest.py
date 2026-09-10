from __future__ import annotations

from datetime import datetime

import pytest
from tests.diff.conftest import load_fixture

from agentdiff.diff.parse import parse_unified_diff
from agentdiff.model import Approval, Change, Comment, CommentState, LineRange, Side

CREATED_AT = datetime(2024, 1, 1, 14, 5, 0)
APPROVED_AT = datetime(2024, 1, 1, 12, 0, 0)

_MISSING = object()


def comment_factory(
    *,
    id: str = "c-1",
    file: str = "src/foo.py",
    range: LineRange | None = _MISSING,
    text: str = "t",
    author: str = "alice",
    state: CommentState = CommentState.ACTIVE,
    thread_id: str | None = None,
    created_at: datetime = CREATED_AT,
) -> Comment:
    if range is _MISSING:
        range = LineRange(side=Side.NEW, start=2, end=2)
    return Comment(
        id=id,
        change_id="chg-01",
        file=file,
        range=range,
        text=text,
        author=author,
        state=state,
        thread_id=thread_id,
        created_at=created_at,
        updated_at=created_at,
    )


def _mixed_comments() -> list[Comment]:
    return [
        comment_factory(
            id="c-new",
            range=LineRange(side=Side.NEW, start=2, end=2),
            text="Fix this",
            author="alice",
        ),
        comment_factory(
            id="c-old-resolved",
            range=LineRange(side=Side.OLD, start=1, end=1),
            text="Old-side note",
            author="bob",
            state=CommentState.RESOLVED,
        ),
        comment_factory(
            id="c-file-level", range=None, text="File-level note", author="carol"
        ),
        comment_factory(
            id="c-drifted",
            range=None,
            text="This anchor drifted",
            author="dave",
            state=CommentState.DRIFTED,
        ),
        comment_factory(
            id="c-thread-1",
            range=LineRange(side=Side.NEW, start=1, end=1),
            text="Threaded reply one",
            author="eve",
            thread_id="t-1",
        ),
        comment_factory(
            id="c-thread-2",
            range=LineRange(side=Side.NEW, start=3, end=3),
            text="Threaded reply two",
            author="frank",
            thread_id="t-1",
        ),
    ]


def _approved_change() -> Change:
    change = parse_unified_diff(load_fixture("basic.patch"))
    return change.model_copy(
        update={
            "id": "chg-01",
            "prev_change": "chg-00",
            "branch": "feat/x",
            "base_revision": "3f2a1b0",
            "head_revision": "9c7d0e1",
            "approval": Approval(
                status="APPROVED",
                message="LGTM, ship it",
                author="alice",
                at=APPROVED_AT,
            ),
        }
    )


@pytest.fixture
def approved_change() -> Change:
    return _approved_change()


@pytest.fixture
def unapproved_change() -> Change:
    return _approved_change().model_copy(update={"approval": None})


@pytest.fixture
def mixed_comments() -> list[Comment]:
    return _mixed_comments()
