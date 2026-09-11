from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from agentdiff.model.types import Approval, Change, Hunk, Line, Side


@pytest.mark.parametrize(
    "kind,old_no,new_no,text,expect_error",
    [
        ("foo", 1, 1, "x", True),
        ("ctx", 1, 1, "x", False),
        ("add", None, 1, "x", False),
        ("del", 1, None, "x", False),
        ("ctx", None, 1, "x", True),
        ("ctx", 1, None, "x", True),
        ("add", 1, 1, "x", True),
        ("del", 1, 1, "x", True),
        ("add", None, 1, "x\n", True),
    ],
    ids=[
        "unknown-kind",
        "ctx-valid",
        "add-valid",
        "del-valid",
        "ctx-missing-old-number",
        "ctx-missing-new-number",
        "add-with-old-number",
        "del-with-new-number",
        "text-with-newline",
    ],
)
def test_line_validation(
    kind: str, old_no: int | None, new_no: int | None, text: str, expect_error: bool
) -> None:
    if expect_error:
        with pytest.raises(ValidationError):
            Line(kind=kind, old_no=old_no, new_no=new_no, text=text)
    else:
        Line(kind=kind, old_no=old_no, new_no=new_no, text=text)


@pytest.mark.parametrize(
    "kwargs,expect_error",
    [
        (
            {
                "old_start": 1,
                "old_count": 2,
                "new_start": 1,
                "new_count": 1,
                "lines": [
                    Line(kind="ctx", old_no=1, new_no=1, text="a"),
                    Line(kind="del", old_no=2, new_no=None, text="b"),
                ],
            },
            False,
        ),
        (
            {
                "old_start": 1,
                "old_count": 1,
                "new_start": 1,
                "new_count": 2,
                "lines": [Line(kind="ctx", old_no=1, new_no=1, text="a")],
            },
            True,
        ),
        (
            {
                "old_start": -1,
                "old_count": 0,
                "new_start": 0,
                "new_count": 0,
                "lines": [],
            },
            True,
        ),
        (
            {
                "old_start": 1,
                "old_count": 2,
                "new_start": 1,
                "new_count": 2,
                "lines": [
                    Line(kind="ctx", old_no=2, new_no=1, text="a"),
                    Line(kind="ctx", old_no=1, new_no=2, text="b"),
                ],
            },
            True,
        ),
    ],
    ids=[
        "counts-consistent",
        "counts-inconsistent",
        "nonnegative-numbers",
        "line-numbers-increasing",
    ],
)
def test_hunk_validation(kwargs: dict[str, object], expect_error: bool) -> None:
    if expect_error:
        with pytest.raises(ValidationError):
            Hunk(**kwargs)
    else:
        Hunk(**kwargs)


def test_change_defaults_and_side_enum() -> None:
    change = Change(id="x")
    assert change.files == []
    assert change.current is None
    assert change.head_revision is None
    assert change.base_revision is None
    assert change.approval is None
    assert change.created_at is None

    assert Side.OLD.value == "OLD"
    assert Side.NEW.value == "NEW"
    assert set(Side) == {Side.OLD, Side.NEW}


def test_approval_shape() -> None:
    approval = Approval(
        status="APPROVED", message="LGTM", author="rkashif", at=datetime(2026, 1, 1)
    )
    assert approval.status == "APPROVED"
    assert approval.message == "LGTM"
