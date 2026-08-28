from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

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


def test_r1_exact_values() -> None:
    assert CommentState.ACTIVE.value == "ACTIVE"
    assert CommentState.RESOLVED.value == "RESOLVED"
    assert CommentState.DRIFTED.value == "DRIFTED"
    assert [m.value for m in CommentState] == ["ACTIVE", "RESOLVED", "DRIFTED"]


def test_r1_str_enum_identity() -> None:
    for member in (CommentState.ACTIVE, CommentState.RESOLVED, CommentState.DRIFTED):
        assert isinstance(member, str)
        assert isinstance(member, CommentState)
    assert CommentState.ACTIVE == "ACTIVE"


def test_r1_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        CommentState("PENDING")
    with pytest.raises(ValueError):
        CommentState(1)


def test_r2_single_line_builds() -> None:
    line_range = LineRange(side=Side.NEW, start=1, end=1)
    assert line_range.start == 1
    assert line_range.end == 1
    assert line_range.side is Side.NEW


def test_r2_span_builds() -> None:
    line_range = LineRange(side=Side.OLD, start=2, end=5)
    assert line_range.start == 2
    assert line_range.end == 5
    assert line_range.side is Side.OLD


def test_r2_accepts_both_sides() -> None:
    LineRange(side=Side.OLD, start=1, end=1)
    LineRange(side=Side.NEW, start=1, end=1)
    with pytest.raises(ValidationError):
        LineRange(side="OLD", start=1, end=1)


def test_r2_zero_start_rejected() -> None:
    with pytest.raises(ValidationError):
        LineRange(side=Side.NEW, start=0, end=1)
    with pytest.raises(ValidationError):
        LineRange(side=Side.NEW, start=0, end=0)


def test_r2_end_before_start_rejected() -> None:
    with pytest.raises(ValidationError):
        LineRange(side=Side.NEW, start=3, end=2)
    with pytest.raises(ValidationError):
        LineRange(side=Side.OLD, start=5, end=4)


def test_r2_negative_numbers_rejected() -> None:
    with pytest.raises(ValidationError):
        LineRange(side=Side.NEW, start=-1, end=1)
    with pytest.raises(ValidationError):
        LineRange(side=Side.NEW, start=1, end=-2)


def test_r2_fields_required() -> None:
    with pytest.raises(ValidationError):
        LineRange()
    with pytest.raises(ValidationError):
        LineRange(start=1, end=1)
    with pytest.raises(ValidationError):
        LineRange(side=Side.NEW, end=1)
    with pytest.raises(ValidationError):
        LineRange(side=Side.NEW, start=1)


def test_r3_line_comment_builds() -> None:
    comment = Comment(**_comment_kwargs())
    assert comment.range == LineRange(side=Side.NEW, start=1, end=3)
    assert comment.range is not None
    assert comment.thread_id is None
    assert comment.anchor_snapshot == []


def test_r3_file_scoped_default() -> None:
    kwargs = _comment_kwargs()
    kwargs.pop("range")
    comment = Comment(**kwargs)
    assert comment.range is None
    assert comment.anchor_snapshot == []


def test_r3_thread_id_optional() -> None:
    with_thread = Comment(**{**_comment_kwargs(), "thread_id": "th-1"})
    without_thread = Comment(**_comment_kwargs())
    assert with_thread.thread_id == "th-1"
    assert without_thread.thread_id is None


def test_r3_required_fields_enforced() -> None:
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


def test_r3_state_must_be_enum() -> None:
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


def test_r4_defaults_to_empty_list() -> None:
    kwargs_a = _comment_kwargs()
    kwargs_a.pop("range")
    kwargs_b = _comment_kwargs()
    kwargs_b.pop("range")
    a = Comment(**kwargs_a)
    b = Comment(**kwargs_b)
    assert a.anchor_snapshot == []
    assert b.anchor_snapshot == []
    assert a.anchor_snapshot is not b.anchor_snapshot


def test_r4_supplied_value_preserved() -> None:
    comment = Comment(
        **{**_comment_kwargs(), "anchor_snapshot": ["line1", "line2", "line3"]}
    )
    assert comment.anchor_snapshot == ["line1", "line2", "line3"]


_ID_RE = re.compile(r"^c-[0-9a-f]{32}$")


def test_r5_prefix_and_format() -> None:
    assert _ID_RE.match(new_comment_id()) is not None


def test_r5_non_deterministic() -> None:
    assert new_comment_id() != new_comment_id()


def test_r5_unique_across_many() -> None:
    ids = {new_comment_id() for _ in range(200)}
    assert len(ids) == 200


def test_r6_new_side_in_bounds() -> None:
    comment = _comment_on(BASIC, "src/foo.py", LineRange(side=Side.NEW, start=3, end=3))
    assert validate_comment(comment, BASIC) is None


def test_r6_old_side_in_bounds() -> None:
    comment = _comment_on(BASIC, "src/foo.py", LineRange(side=Side.OLD, start=2, end=2))
    assert validate_comment(comment, BASIC) is None


def test_r6_multiple_hunks_second_region() -> None:
    comment = _comment_on(
        MULTIPLE_HUNKS, "m.txt", LineRange(side=Side.NEW, start=19, end=25)
    )
    assert validate_comment(comment, MULTIPLE_HUNKS) is None


def test_r6_multiple_hunks_old_region() -> None:
    comment = _comment_on(
        MULTIPLE_HUNKS, "m.txt", LineRange(side=Side.OLD, start=19, end=25)
    )
    assert validate_comment(comment, MULTIPLE_HUNKS) is None


def test_r6_multiple_hunks_first_region() -> None:
    comment = _comment_on(
        MULTIPLE_HUNKS, "m.txt", LineRange(side=Side.NEW, start=1, end=6)
    )
    assert validate_comment(comment, MULTIPLE_HUNKS) is None


def test_r6_deleted_file_old_side_valid() -> None:
    comment = _comment_on(
        DELETED_FILE, "old.txt", LineRange(side=Side.OLD, start=1, end=3)
    )
    assert validate_comment(comment, DELETED_FILE) is None


def test_r6_new_file_new_side_valid() -> None:
    comment = _comment_on(NEW_FILE, "new.txt", LineRange(side=Side.NEW, start=1, end=3))
    assert validate_comment(comment, NEW_FILE) is None


def test_r6_file_level_valid_basic() -> None:
    assert validate_comment(_comment_on(BASIC, "src/foo.py", None), BASIC) is None


def test_r6_file_level_valid_binary() -> None:
    assert validate_comment(_comment_on(BINARY, "img.bin", None), BINARY) is None


def test_r6_file_level_valid_mode_only() -> None:
    assert (
        validate_comment(_comment_on(MODE_ONLY, "script.sh", None), MODE_ONLY) is None
    )


def test_r6_missing_file_line_comment() -> None:
    comment = _comment_on(BASIC, "nope.py", LineRange(side=Side.NEW, start=1, end=1))
    with pytest.raises(CommentValidationError):
        validate_comment(comment, BASIC)


def test_r6_missing_file_file_level() -> None:
    with pytest.raises(CommentValidationError):
        validate_comment(_comment_on(BASIC, "nope.py", None), BASIC)


def test_r6_new_side_out_of_range() -> None:
    comment = _comment_on(BASIC, "src/foo.py", LineRange(side=Side.NEW, start=3, end=4))
    with pytest.raises(CommentValidationError):
        validate_comment(comment, BASIC)


def test_r6_old_side_out_of_range() -> None:
    comment = _comment_on(BASIC, "src/foo.py", LineRange(side=Side.OLD, start=2, end=4))
    with pytest.raises(CommentValidationError):
        validate_comment(comment, BASIC)


def test_r6_out_of_range_beyond_any_hunk() -> None:
    comment = _comment_on(
        MULTIPLE_HUNKS, "m.txt", LineRange(side=Side.NEW, start=26, end=26)
    )
    with pytest.raises(CommentValidationError):
        validate_comment(comment, MULTIPLE_HUNKS)


def test_r6_binary_file_line_range_rejected() -> None:
    comment = _comment_on(BINARY, "img.bin", LineRange(side=Side.NEW, start=1, end=1))
    with pytest.raises(CommentValidationError):
        validate_comment(comment, BINARY)


def test_r6_binary_file_old_side_rejected() -> None:
    comment = _comment_on(BINARY, "img.bin", LineRange(side=Side.OLD, start=1, end=1))
    with pytest.raises(CommentValidationError):
        validate_comment(comment, BINARY)


def test_r6_mode_only_file_range_rejected() -> None:
    comment = _comment_on(
        MODE_ONLY, "script.sh", LineRange(side=Side.NEW, start=1, end=1)
    )
    with pytest.raises(CommentValidationError):
        validate_comment(comment, MODE_ONLY)


def test_r6_rename_file_range_rejected() -> None:
    comment = _comment_on(RENAME, "new.py", LineRange(side=Side.NEW, start=1, end=1))
    with pytest.raises(CommentValidationError):
        validate_comment(comment, RENAME)
    assert validate_comment(_comment_on(RENAME, "new.py", None), RENAME) is None


def test_r6_deleted_file_new_side_rejected() -> None:
    comment = _comment_on(
        DELETED_FILE, "old.txt", LineRange(side=Side.NEW, start=1, end=1)
    )
    with pytest.raises(CommentValidationError):
        validate_comment(comment, DELETED_FILE)


def test_r6_new_file_old_side_rejected() -> None:
    comment = _comment_on(NEW_FILE, "new.txt", LineRange(side=Side.OLD, start=1, end=1))
    with pytest.raises(CommentValidationError):
        validate_comment(comment, NEW_FILE)


def test_r6_error_is_typed_and_messages_are_informative() -> None:
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


def test_r7_exports_present() -> None:
    import agentdiff.model as m

    for name in [
        "Comment",
        "CommentState",
        "LineRange",
        "new_comment_id",
        "validate_comment",
        "CommentValidationError",
    ]:
        assert hasattr(m, name)
        assert name in m.__all__


def test_r7_internals_hidden() -> None:
    import agentdiff.model as m
    import agentdiff.model.validate as v

    assert not hasattr(m, "_max_line")
    assert "_max_line" not in m.__all__
    assert m.validate_comment is v.validate_comment


def _thread_comment(comment_id: str, thread_id: str | None = None) -> Comment:
    return Comment(
        id=comment_id,
        change_id="chg",
        file="src/foo.py",
        text=comment_id,
        author="a",
        thread_id=thread_id,
        state=CommentState.ACTIVE,
        created_at=datetime(2024, 1, 1),
        updated_at=datetime(2024, 1, 1),
    )


def test_r8_thread_grouping_by_thread_id() -> None:
    top = _thread_comment("top")
    reply_a = _thread_comment("r1", thread_id="th-42")
    reply_b = _thread_comment("r2", thread_id="th-42")
    groups: dict[str | None, list[str]] = {}
    [groups.setdefault(c.thread_id, []).append(c.id) for c in [top, reply_a, reply_b]]
    assert groups[None] == ["top"]
    assert groups["th-42"] == ["r1", "r2"]


def test_r8_many_threads_group_separately() -> None:
    comments = [
        _thread_comment("a", thread_id="th-1"),
        _thread_comment("b", thread_id="th-1"),
        _thread_comment("c", thread_id="th-2"),
        _thread_comment("d"),
    ]
    groups: dict[str | None, list[str]] = {}
    [groups.setdefault(c.thread_id, []).append(c.id) for c in comments]
    assert set(groups) == {"th-1", "th-2", None}
    assert len(groups["th-1"]) == 2
    assert len(groups["th-2"]) == 1
    assert len(groups[None]) == 1


def test_r8_built_from_real_fixtures() -> None:
    source = Path(__file__).read_text(encoding="utf-8")
    assert "load_fixture(" in source
    assert "parse_unified_diff(" in source
    for name in ("Change", "Hunk"):
        assert f"{name}(" not in source
