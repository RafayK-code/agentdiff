from __future__ import annotations

import copy
import inspect
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from tests.diff.conftest import load_fixture
from tests.export.conftest import comment_factory

from agentdiff.diff.parse import parse_unified_diff
from agentdiff.export import SCHEMA_VERSION, export_json
from agentdiff.model import Change, Comment, CommentState, LineRange, Side

RE_SEMVER = re.compile(r"\d+\.\d+\.\d+")
FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_api_signature() -> None:
    import agentdiff.export as export

    sig = inspect.signature(export.export_json)
    assert list(sig.parameters) == ["change", "comments"]
    assert all(
        p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
        for p in sig.parameters.values()
    )
    assert {"SCHEMA_VERSION", "export_json", "export_markdown"} <= set(export.__all__)


def test_schema_version_constant() -> None:
    assert type(SCHEMA_VERSION) is str
    assert re.fullmatch(RE_SEMVER, SCHEMA_VERSION) is not None


def test_output_is_pure(approved_change, mixed_comments: list[Comment]) -> None:
    change_copy = copy.deepcopy(approved_change)
    comments_copy = copy.deepcopy(mixed_comments)
    out1 = export_json(approved_change, mixed_comments)
    out2 = export_json(approved_change, mixed_comments)
    assert out1 == out2
    assert approved_change == change_copy
    assert mixed_comments == comments_copy


def test_approval_absent_is_null(
    unapproved_change, mixed_comments: list[Comment]
) -> None:
    out = export_json(unapproved_change, mixed_comments)
    parsed = json.loads(out)["change"]
    assert parsed["approval"] is None
    assert '"approval": null' in out


@pytest.mark.parametrize(
    "name,expected,no_context",
    [
        (
            "basic.patch",
            {"path": "src/foo.py", "additions": 1, "deletions": 1, "old_path": None},
            True,
        ),
        (
            "multiple_hunks.patch",
            {"path": "m.txt", "additions": 2, "deletions": 2, "old_path": None},
            False,
        ),
        (
            "new_file.patch",
            {"path": "new.txt", "additions": 3, "deletions": 0, "old_path": None},
            False,
        ),
        (
            "deleted_file.patch",
            {"path": "old.txt", "additions": 0, "deletions": 3, "old_path": None},
            False,
        ),
        (
            "rename.patch",
            {"path": "new.py", "additions": 0, "deletions": 0, "old_path": "old.py"},
            False,
        ),
        (
            "mode_only.patch",
            {"path": "script.sh", "additions": 0, "deletions": 0, "old_path": None},
            False,
        ),
        (
            "binary.patch",
            {"path": "img.bin", "additions": 0, "deletions": 0, "old_path": None},
            False,
        ),
        (
            "rename_modify.patch",
            {"path": "new.py", "additions": 1, "deletions": 1, "old_path": "old.py"},
            False,
        ),
        (
            "single_line.patch",
            {"path": "s.txt", "additions": 1, "deletions": 1, "old_path": None},
            False,
        ),
    ],
    ids=[
        "basic",
        "multiple-hunks",
        "new-file",
        "deleted-file",
        "rename",
        "mode-only",
        "binary",
        "old-path-set",
        "single-line-change",
    ],
)
def test_counting(name: str, expected: dict[str, object], no_context: bool) -> None:
    change = parse_unified_diff(load_fixture(name))
    out = export_json(change, [])
    files = json.loads(out)["change"]["files"]
    assert len(files) == 1
    assert files[0] == expected
    if no_context:
        assert "ctx1" not in out
        assert "ctx2" not in out


def test_empty_files_list() -> None:
    change = Change(id="chg-empty", files=[])
    parsed = json.loads(export_json(change, []))
    assert parsed["change"]["files"] == []
    assert parsed["comments"] == []


def test_single_line_range_inclusive(approved_change) -> None:
    comment = comment_factory(
        id="c-300", range=LineRange(side=Side.NEW, start=300, end=364)
    )
    exported = json.loads(export_json(approved_change, [comment]))["comments"][0]
    assert exported["lines"] == [300, 364]


def test_old_side_multi_line(approved_change) -> None:
    comment = comment_factory(
        id="c-old", range=LineRange(side=Side.OLD, start=1, end=3)
    )
    exported = json.loads(export_json(approved_change, [comment]))["comments"][0]
    assert exported["side"] == "OLD"
    assert exported["lines"] == [1, 3]


def test_file_level_comment_nulls(approved_change) -> None:
    comment = comment_factory(id="c-file", range=None)
    out = export_json(approved_change, [comment])
    exported = json.loads(out)["comments"][0]
    assert exported["side"] is None
    assert exported["lines"] is None
    assert '"side": null' in out
    assert '"lines": null' in out
    for key in ("file", "text", "author", "state", "drifted", "created_at"):
        assert key in exported


def test_drifted_derived_not_set(approved_change) -> None:
    comment = comment_factory(id="c-active", state=CommentState.ACTIVE)
    object.__setattr__(comment, "drifted", True)
    exported = json.loads(export_json(approved_change, [comment]))["comments"][0]
    assert exported["drifted"] is False


def test_comment_order_preserved(
    approved_change, mixed_comments: list[Comment]
) -> None:
    by_id = {c.id: c for c in mixed_comments}
    reordered = [by_id["c-old-resolved"], by_id["c-file-level"], by_id["c-new"]]
    doc = json.loads(export_json(approved_change, reordered))
    assert [c["id"] for c in doc["comments"]] == [
        "c-old-resolved",
        "c-file-level",
        "c-new",
    ]


@pytest.mark.parametrize(
    "created_at,expected",
    [
        (datetime(2024, 1, 1, 14, 5, 30), "2024-01-01T14:05:30Z"),
        (
            datetime(2024, 1, 1, 9, 5, 30, tzinfo=timezone(timedelta(hours=-5))),
            "2024-01-01T14:05:30Z",
        ),
        (datetime(2024, 1, 1, 14, 5, 30, 123456), "2024-01-01T14:05:30Z"),
    ],
    ids=["naive-utc", "aware-converted", "microseconds-truncated"],
)
def test_created_at_serialization(
    approved_change, created_at: datetime, expected: str
) -> None:
    comment = comment_factory(id="c-ts", created_at=created_at)
    exported = json.loads(export_json(approved_change, [comment]))["comments"][0]
    assert exported["created_at"] == expected


def test_unicode_escaped_ascii(approved_change) -> None:
    comment = comment_factory(id="c-u", text="café ☕", author="joán")
    out = export_json(approved_change, [comment])
    assert '"caf\\u00e9 \\u2615"' in out
    assert '"jo\\u00e1n"' in out
    exported = json.loads(out)["comments"][0]
    assert exported["text"] == "café ☕"
    assert exported["author"] == "joán"


def test_golden_exact_match(approved_change, mixed_comments: list[Comment]) -> None:
    expected = (FIXTURES_DIR / "expected.json").read_text(encoding="utf-8")
    assert export_json(approved_change, mixed_comments) == expected


def test_golden_round_trips(approved_change, mixed_comments: list[Comment]) -> None:
    doc = json.loads(export_json(approved_change, mixed_comments))
    assert len(doc["change"]["files"]) == len(approved_change.files)
    assert len(doc["comments"]) == len(mixed_comments)
    paths = {f["path"] for f in doc["change"]["files"]}
    for comment in doc["comments"]:
        assert comment["file"] in paths


def test_change_block_chain_fields(
    approved_change, mixed_comments: list[Comment]
) -> None:
    parsed = json.loads(export_json(approved_change, mixed_comments))["change"]
    assert list(parsed.keys()) == [
        "id",
        "prev_change",
        "branch",
        "base_revision",
        "head_revision",
        "approval",
        "files",
    ]
    assert parsed["prev_change"] == "chg-00"
    assert parsed["branch"] == "feat/x"


def test_chain_head_emits_null_chain_fields() -> None:
    head_out = export_json(parse_unified_diff(load_fixture("basic.patch")), [])
    assert json.loads(head_out)["schema_version"] == SCHEMA_VERSION
    assert '"prev_change": null' in head_out
    assert '"branch": null' in head_out
