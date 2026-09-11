from __future__ import annotations

from datetime import datetime

import pytest
from tests.diff.conftest import load_fixture

from agentdiff.diff.parse import parse_unified_diff
from agentdiff.model import (
    Approval,
    Change,
    Comment,
    CommentState,
    LineRange,
    Side,
    Version,
)

CREATED_AT = datetime(2024, 1, 1, 14, 5, 0)
APPROVED_AT = datetime(2024, 1, 1, 12, 0, 0)

REV_1 = "9c7d0e1"
REV_2 = "a1b2c3d"

_MISSING = object()


def comment_factory(
    *,
    id: str = "c-1",
    revision: str = REV_2,
    file: str = "src/foo.py",
    range: LineRange | None = _MISSING,
    text: str = "t",
    author: str = "alice",
    state: CommentState = CommentState.ACTIVE,
    drifted: bool = False,
    in_reply_to: str | None = None,
    created_at: datetime = CREATED_AT,
) -> Comment:
    if range is _MISSING:
        range = LineRange(side=Side.NEW, start=2, end=2)
    return Comment(
        id=id,
        change_id="chg-01",
        revision=revision,
        file=file,
        range=range,
        text=text,
        author=author,
        state=state,
        drifted=drifted,
        in_reply_to=in_reply_to,
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
            revision=REV_1,
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
            state=CommentState.ACTIVE,
            drifted=True,
        ),
        comment_factory(
            id="c-closed",
            range=None,
            text="Closed note",
            author="grace",
            state=CommentState.CLOSED,
            drifted=False,
        ),
        comment_factory(
            id="c-thread-1",
            range=LineRange(side=Side.NEW, start=1, end=1),
            text="Threaded reply one",
            author="eve",
        ),
        comment_factory(
            id="c-thread-2",
            range=LineRange(side=Side.NEW, start=3, end=3),
            text="Threaded reply two",
            author="frank",
            in_reply_to="c-thread-1",
        ),
    ]


def _approved_change() -> Change:
    basic_files = parse_unified_diff(load_fixture("basic.patch")).files
    return Change(
        id="chg-01",
        branch="feat/x",
        base_revision="3f2a1b0",
        versions=[
            Version(revision=REV_1, files=basic_files),
            Version(revision=REV_2, files=basic_files),
        ],
        approval=Approval(
            status="APPROVED",
            message="LGTM, ship it",
            author="alice",
            at=APPROVED_AT,
        ),
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
