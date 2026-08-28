from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from agentdiff.model.types import Approval, Change, FileDiff, Hunk, Line, Side


def test_r2_line_kind_literal() -> None:
    with pytest.raises(ValidationError):
        Line(kind="foo", old_no=1, new_no=1, text="x")
    Line(kind="ctx", old_no=1, new_no=1, text="x")
    Line(kind="add", old_no=None, new_no=1, text="x")
    Line(kind="del", old_no=1, new_no=None, text="x")


def test_r2_line_ctx_requires_both_numbers() -> None:
    with pytest.raises(ValidationError):
        Line(kind="ctx", old_no=None, new_no=1, text="x")
    with pytest.raises(ValidationError):
        Line(kind="ctx", old_no=1, new_no=None, text="x")


def test_r2_line_add_no_old_no() -> None:
    with pytest.raises(ValidationError):
        Line(kind="add", old_no=1, new_no=1, text="x")


def test_r2_line_del_no_new_no() -> None:
    with pytest.raises(ValidationError):
        Line(kind="del", old_no=1, new_no=1, text="x")


def test_r2_line_text_no_newline() -> None:
    with pytest.raises(ValidationError):
        Line(kind="add", old_no=None, new_no=1, text="x\n")


def test_r2_hunk_counts_consistent() -> None:
    Hunk(
        old_start=1,
        old_count=2,
        new_start=1,
        new_count=1,
        lines=[
            Line(kind="ctx", old_no=1, new_no=1, text="a"),
            Line(kind="del", old_no=2, new_no=None, text="b"),
        ],
    )


def test_r2_hunk_counts_inconsistent() -> None:
    with pytest.raises(ValidationError):
        Hunk(
            old_start=1,
            old_count=1,
            new_start=1,
            new_count=2,
            lines=[Line(kind="ctx", old_no=1, new_no=1, text="a")],
        )


def test_r2_hunk_nonnegative_numbers() -> None:
    with pytest.raises(ValidationError):
        Hunk(old_start=-1, old_count=0, new_start=0, new_count=0, lines=[])


def test_r2_hunk_line_numbers_increasing() -> None:
    with pytest.raises(ValidationError):
        Hunk(
            old_start=1,
            old_count=2,
            new_start=1,
            new_count=2,
            lines=[
                Line(kind="ctx", old_no=2, new_no=1, text="a"),
                Line(kind="ctx", old_no=1, new_no=2, text="b"),
            ],
        )


def test_r2_change_defaults() -> None:
    change = Change(id="x", files=[])
    assert change.base_revision is None
    assert change.head_revision is None
    assert change.approval is None
    assert change.created_at is None


def test_r2_side_enum() -> None:
    assert Side.OLD.value == "OLD"
    assert Side.NEW.value == "NEW"
    assert set(Side) == {Side.OLD, Side.NEW}


def test_r2_model_re_export() -> None:
    from agentdiff.model import Change as BridgeChange
    from agentdiff.model import FileDiff as BridgeFileDiff
    from agentdiff.model import Hunk as BridgeHunk
    from agentdiff.model import Line as BridgeLine
    from agentdiff.model import Side as BridgeSide

    assert BridgeChange is Change
    assert BridgeFileDiff is FileDiff
    assert BridgeHunk is Hunk
    assert BridgeLine is Line
    assert BridgeSide is Side


def test_approval_shape() -> None:
    approval = Approval(
        status="APPROVED", message="LGTM", author="rkashif", at=datetime(2026, 1, 1)
    )
    assert approval.status == "APPROVED"
    assert approval.message == "LGTM"
