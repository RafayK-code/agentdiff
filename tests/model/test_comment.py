from __future__ import annotations

import re
from datetime import datetime

import pytest
from pydantic import ValidationError
from tests.diff.conftest import load_fixture

from agentdiff.diff.parse import parse_unified_diff
from agentdiff.model import (
    Change,
    Comment,
    CommentState,
    CommentValidationError,
    LineRange,
    Side,
    new_comment_id,
    validate_comment,
)

BASIC = parse_unified_diff(load_fixture("basic.patch"))
MULTIPLE_HUNKS = parse_unified_diff(load_fixture("multiple_hunks.patch"))
NEW_FILE = parse_unified_diff(load_fixture("new_file.patch"))
DELETED_FILE = parse_unified_diff(load_fixture("deleted_file.patch"))
BINARY = parse_unified_diff(load_fixture("binary.patch"))
MODE_ONLY = parse_unified_diff(load_fixture("mode_only.patch"))
RENAME = parse_unified_diff(load_fixture("rename.patch"))


def _comment_kwargs() -> dict[str, object]:
    return {
        "id": "c-a",
        "change_id": "chg-x",
        "file": "src/foo.py",
        "range": LineRange(side=Side.NEW, start=1, end=3),
        "text": "rename this",
        "author": "alice",
        "state": CommentState.ACTIVE,
        "created_at": datetime(2024, 1, 1, 12, 0),
        "updated_at": datetime(2024, 1, 1, 12, 5),
    }


def _comment_on(
    change: Change,
    file: str,
    line_range: LineRange | None,
    *,
    text: str = "t",
) -> Comment:
    return Comment(
        id="c",
        change_id=change.id,
        file=file,
        range=line_range,
        text=text,
        author="a",
        state=CommentState.ACTIVE,
        created_at=datetime(2024, 1, 1),
        updated_at=datetime(2024, 1, 1),
    )


def test_comment_state() -> None:
    assert CommentState.ACTIVE.value == "ACTIVE"
    assert CommentState.RESOLVED.value == "RESOLVED"
    assert CommentState.DRIFTED.value == "DRIFTED"
    assert [m.value for m in CommentState] == ["ACTIVE", "RESOLVED", "DRIFTED"]
    for member in (CommentState.ACTIVE, CommentState.RESOLVED, CommentState.DRIFTED):
        assert isinstance(member, str)
        assert isinstance(member, CommentState)
    assert CommentState.ACTIVE == "ACTIVE"
    with pytest.raises(ValueError):
        CommentState("PENDING")
    with pytest.raises(ValueError):
        CommentState(1)


def test_line_range_accepts_valid() -> None:
    span = LineRange(side=Side.OLD, start=2, end=5)
    assert span.start == 2
    assert span.end == 5
    assert span.side is Side.OLD
    LineRange(side=Side.OLD, start=1, end=1)
    LineRange(side=Side.NEW, start=1, end=1)
    with pytest.raises(ValidationError):
        LineRange(side="OLD", start=1, end=1)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"side": Side.NEW, "start": 0, "end": 1},
        {"side": Side.NEW, "start": 0, "end": 0},
        {"side": Side.NEW, "start": 3, "end": 2},
        {"side": Side.OLD, "start": 5, "end": 4},
        {"side": Side.NEW, "start": -1, "end": 1},
        {"side": Side.NEW, "start": 1, "end": -2},
        {},
        {"start": 1, "end": 1},
        {"side": Side.NEW, "end": 1},
        {"side": Side.NEW, "start": 1},
    ],
    ids=[
        "zero-start",
        "zero-to-zero",
        "end-before-start",
        "old-end-before-start",
        "negative-start",
        "negative-end",
        "all-fields-missing",
        "side-missing",
        "start-missing",
        "end-missing",
    ],
)
def test_line_range_rejects_invalid(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        LineRange(**kwargs)


def test_comment_constructs() -> None:
    comment = Comment(**_comment_kwargs())
    assert comment.range == LineRange(side=Side.NEW, start=1, end=3)
    assert comment.range is not None
    assert comment.thread_id is None
    assert comment.anchor_snapshot == []

    file_scoped = _comment_kwargs()
    file_scoped.pop("range")
    comment = Comment(**file_scoped)
    assert comment.range is None
    assert comment.anchor_snapshot == []

    with_thread = Comment(**{**_comment_kwargs(), "thread_id": "th-1"})
    without_thread = Comment(**_comment_kwargs())
    assert with_thread.thread_id == "th-1"
    assert without_thread.thread_id is None

    kwargs_a = _comment_kwargs()
    kwargs_a.pop("range")
    kwargs_b = _comment_kwargs()
    kwargs_b.pop("range")
    a = Comment(**kwargs_a)
    b = Comment(**kwargs_b)
    assert a.anchor_snapshot == []
    assert b.anchor_snapshot == []
    assert a.anchor_snapshot is not b.anchor_snapshot

    supplied = Comment(
        **{**_comment_kwargs(), "anchor_snapshot": ["line1", "line2", "line3"]}
    )
    assert supplied.anchor_snapshot == ["line1", "line2", "line3"]


def test_comment_rejects_invalid_fields() -> None:
    for field in [
        "id",
        "change_id",
        "file",
        "text",
        "author",
        "state",
        "created_at",
        "updated_at",
    ]:
        kwargs = _comment_kwargs()
        kwargs.pop(field)
        with pytest.raises(ValidationError):
            Comment(**kwargs)

    with pytest.raises(ValidationError):
        Comment(
            id="c",
            change_id="chg",
            file="f",
            text="t",
            author="a",
            state="ACTIVE",
            created_at=datetime(2024, 1, 1),
            updated_at=datetime(2024, 1, 1),
        )


_ID_RE = re.compile(r"^c-[0-9a-f]{32}$")


def test_new_comment_id() -> None:
    assert _ID_RE.match(new_comment_id()) is not None
    assert new_comment_id() != new_comment_id()
    ids = {new_comment_id() for _ in range(200)}
    assert len(ids) == 200


@pytest.mark.parametrize(
    "change,file,line_range",
    [
        (BASIC, "src/foo.py", LineRange(side=Side.NEW, start=3, end=3)),
        (BASIC, "src/foo.py", LineRange(side=Side.OLD, start=2, end=2)),
        (MULTIPLE_HUNKS, "m.txt", LineRange(side=Side.NEW, start=19, end=25)),
        (MULTIPLE_HUNKS, "m.txt", LineRange(side=Side.OLD, start=19, end=25)),
        (MULTIPLE_HUNKS, "m.txt", LineRange(side=Side.NEW, start=1, end=6)),
        (DELETED_FILE, "old.txt", LineRange(side=Side.OLD, start=1, end=3)),
        (NEW_FILE, "new.txt", LineRange(side=Side.NEW, start=1, end=3)),
        (BASIC, "src/foo.py", None),
        (BINARY, "img.bin", None),
        (MODE_ONLY, "script.sh", None),
        (RENAME, "new.py", None),
    ],
    ids=[
        "new-side-in-bounds",
        "old-side-in-bounds",
        "second-hunk-new-side",
        "second-hunk-old-side",
        "first-hunk-new-side",
        "deleted-file-old-side",
        "new-file-new-side",
        "file-level-basic",
        "file-level-binary",
        "file-level-mode-only",
        "file-level-rename",
    ],
)
def test_validate_accepts_valid_comments(
    change: Change, file: str, line_range: LineRange | None
) -> None:
    comment = _comment_on(change, file, line_range)
    assert validate_comment(comment, change) is None


@pytest.mark.parametrize(
    "change,file,line_range",
    [
        (BASIC, "nope.py", LineRange(side=Side.NEW, start=1, end=1)),
        (BASIC, "nope.py", None),
        (BASIC, "src/foo.py", LineRange(side=Side.NEW, start=3, end=4)),
        (BASIC, "src/foo.py", LineRange(side=Side.OLD, start=2, end=4)),
        (MULTIPLE_HUNKS, "m.txt", LineRange(side=Side.NEW, start=26, end=26)),
        (BINARY, "img.bin", LineRange(side=Side.NEW, start=1, end=1)),
        (BINARY, "img.bin", LineRange(side=Side.OLD, start=1, end=1)),
        (MODE_ONLY, "script.sh", LineRange(side=Side.NEW, start=1, end=1)),
        (RENAME, "new.py", LineRange(side=Side.NEW, start=1, end=1)),
        (DELETED_FILE, "old.txt", LineRange(side=Side.NEW, start=1, end=1)),
        (NEW_FILE, "new.txt", LineRange(side=Side.OLD, start=1, end=1)),
    ],
    ids=[
        "missing-file-line-comment",
        "missing-file-file-level",
        "new-side-out-of-range",
        "old-side-out-of-range",
        "beyond-any-hunk",
        "binary-new-side",
        "binary-old-side",
        "mode-only-range",
        "rename-range",
        "deleted-file-new-side",
        "new-file-old-side",
    ],
)
def test_validate_rejects_invalid_comments(
    change: Change, file: str, line_range: LineRange | None
) -> None:
    comment = _comment_on(change, file, line_range)
    with pytest.raises(CommentValidationError):
        validate_comment(comment, change)


def test_validate_error_is_typed_and_informative() -> None:
    missing = _comment_on(BASIC, "nope.py", LineRange(side=Side.NEW, start=1, end=1))
    with pytest.raises(CommentValidationError) as exc1:
        validate_comment(missing, BASIC)
    out_of_range = _comment_on(
        BASIC, "src/foo.py", LineRange(side=Side.NEW, start=3, end=4)
    )
    with pytest.raises(CommentValidationError) as exc2:
        validate_comment(out_of_range, BASIC)
    assert type(exc1.value).__name__ == "CommentValidationError"
    assert issubclass(CommentValidationError, ValueError)
    assert "nope.py" in str(exc1.value)
    assert "range" in str(exc2.value)
    assert "3" in str(exc2.value)
