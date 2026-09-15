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
from agentdiff.export import SCHEMA_VERSION, export_json, export_markdown
from agentdiff.model import (
    Change,
    Comment,
    CommentState,
    LineRange,
    Side,
    Version,
)

RE_SEMVER = re.compile(r"\d+\.\d+\.\d+")
FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_api_signature() -> None:
    import agentdiff.export as export

    sig = inspect.signature(export.export_json)
    assert list(sig.parameters) == ["change", "comments", "include_closed"]
    assert sig.parameters["change"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert sig.parameters["comments"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert sig.parameters["include_closed"].kind is inspect.Parameter.KEYWORD_ONLY
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
    change = Change(id="chg-empty")
    parsed = json.loads(export_json(change, []))
    assert parsed["change"]["files"] == []
    assert parsed["change"]["versions"] == []
    assert parsed["change"]["current_revision"] is None
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


def test_export_context_projects_stored_snapshot() -> None:
    now = datetime(2020, 1, 1, tzinfo=timezone.utc)
    change = Change(
        id="chg-s",
        versions=[
            Version(
                revision="rev-1",
                files=parse_unified_diff(load_fixture("basic.patch")).files,
            )
        ],
    )
    old = Comment(
        id="c-old",
        change_id="chg-s",
        revision="rev-1",
        file="src/foo.py",
        range=LineRange(side=Side.OLD, start=2, end=2),
        text="old side",
        author="alice",
        state=CommentState.ACTIVE,
        created_at=now,
        updated_at=now,
        anchor_snapshot=["SNAPSHOT-ONLY"],
    )
    new = Comment(
        id="c-new",
        change_id="chg-s",
        revision="rev-1",
        file="src/foo.py",
        range=LineRange(side=Side.NEW, start=2, end=2),
        text="new side",
        author="alice",
        state=CommentState.ACTIVE,
        created_at=now,
        updated_at=now,
        anchor_snapshot=["added"],
    )

    doc = json.loads(export_json(change, [old, new]))
    blocks = {c["id"]: c for c in doc["comments"]}

    assert blocks["c-old"]["context"] == ["SNAPSHOT-ONLY"]
    assert blocks["c-new"]["context"] == ["added"]
    assert blocks["c-old"]["side"] == "OLD"
    assert blocks["c-old"]["lines"] == [2, 2]
    assert list(blocks["c-old"].keys()) == [
        "id",
        "revision",
        "file",
        "side",
        "lines",
        "context",
        "text",
        "author",
        "role",
        "in_reply_to",
        "state",
        "drifted",
        "created_at",
    ]
    assert doc["schema_version"] == "1.0.0"


def test_export_context_file_level_empty() -> None:
    now = datetime(2020, 1, 1, tzinfo=timezone.utc)
    change = Change(
        id="chg-s",
        versions=[
            Version(
                revision="rev-1",
                files=parse_unified_diff(load_fixture("basic.patch")).files,
            )
        ],
    )
    file_level = Comment(
        id="c-file",
        change_id="chg-s",
        revision="rev-1",
        file="src/foo.py",
        range=None,
        text="file note",
        author="alice",
        state=CommentState.ACTIVE,
        created_at=now,
        updated_at=now,
        anchor_snapshot=[],
    )

    out = export_json(change, [file_level])
    block = json.loads(out)["comments"][0]

    assert block["context"] == []
    assert block["side"] is None
    assert block["lines"] is None
    assert '"context": []' in out


def test_export_json_real_drifted(approved_change) -> None:
    comments = [
        comment_factory(id="c-active-drift", state=CommentState.ACTIVE, drifted=True),
        comment_factory(
            id="c-resolved-drift", state=CommentState.RESOLVED, drifted=True
        ),
        comment_factory(id="c-active-clean", state=CommentState.ACTIVE, drifted=False),
    ]
    doc = json.loads(export_json(approved_change, comments))
    by_id = {c["id"]: c for c in doc["comments"]}
    assert by_id["c-active-drift"]["drifted"] is True
    assert by_id["c-active-drift"]["state"] == "ACTIVE"
    assert by_id["c-resolved-drift"]["drifted"] is True
    assert by_id["c-resolved-drift"]["state"] == "RESOLVED"
    assert by_id["c-active-clean"]["drifted"] is False
    assert by_id["c-active-clean"]["state"] == "ACTIVE"


def test_export_json_omits_closed_by_default(approved_change) -> None:
    comments = [
        comment_factory(id="c-a", state=CommentState.ACTIVE),
        comment_factory(id="c-c", state=CommentState.CLOSED),
    ]
    out_default = export_json(approved_change, comments)
    out_all = export_json(approved_change, comments, include_closed=True)
    assert [c["id"] for c in json.loads(out_default)["comments"]] == ["c-a"]
    doc_all = json.loads(out_all)
    assert [c["id"] for c in doc_all["comments"]] == ["c-a", "c-c"]
    closed = doc_all["comments"][1]
    assert closed["state"] == "CLOSED"
    assert closed["drifted"] is False
    assert json.loads(out_default)["schema_version"] == SCHEMA_VERSION
    assert doc_all["schema_version"] == SCHEMA_VERSION


def test_schema_version_unchanged(approved_change) -> None:
    assert SCHEMA_VERSION == "1.0.0"
    assert json.loads(export_json(approved_change, []))["schema_version"] == "1.0.0"


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
    assert export_json(approved_change, mixed_comments, include_closed=True) == expected


def test_golden_round_trips(approved_change, mixed_comments: list[Comment]) -> None:
    doc = json.loads(export_json(approved_change, mixed_comments, include_closed=True))
    assert len(doc["change"]["files"]) == len(approved_change.files)
    assert len(doc["comments"]) == len(mixed_comments)
    paths = {f["path"] for f in doc["change"]["files"]}
    for comment in doc["comments"]:
        assert comment["file"] in paths


def test_change_block_fields(approved_change, mixed_comments: list[Comment]) -> None:
    parsed = json.loads(export_json(approved_change, mixed_comments))["change"]
    assert list(parsed.keys()) == [
        "id",
        "branch",
        "base_revision",
        "current_revision",
        "versions",
        "approval",
        "files",
    ]
    assert parsed["branch"] == "feat/x"
    assert parsed["base_revision"] == "3f2a1b0"
    assert parsed["current_revision"] == "a1b2c3d"
    assert parsed["versions"] == ["9c7d0e1", "a1b2c3d"]
    assert "prev_change" not in parsed
    assert "head_revision" not in parsed


def test_patch_import_emits_null_provenance() -> None:
    head_out = export_json(parse_unified_diff(load_fixture("basic.patch")), [])
    parsed = json.loads(head_out)
    assert parsed["schema_version"] == SCHEMA_VERSION
    assert parsed["change"]["branch"] is None
    assert parsed["change"]["base_revision"] is None
    assert parsed["change"]["current_revision"] is not None
    assert len(parsed["change"]["versions"]) == 1


def test_export_json_shape_and_closed() -> None:
    change = Change(
        id="chg-s",
        branch="feat/x",
        base_revision="base",
        versions=[
            Version(
                revision="rev-1",
                files=parse_unified_diff(load_fixture("basic.patch")).files,
            ),
            Version(
                revision="rev-2",
                files=parse_unified_diff(load_fixture("new_file.patch")).files,
            ),
        ],
    )
    root = comment_factory(id="c-root", revision="rev-2", file="new.txt", range=None)
    reply = comment_factory(
        id="c-reply",
        revision="rev-2",
        file="new.txt",
        range=None,
        in_reply_to="c-root",
    )
    closed = comment_factory(
        id="c-closed",
        revision="rev-1",
        file="new.txt",
        range=None,
        state=CommentState.CLOSED,
    )
    comments = [root, reply, closed]

    default = json.loads(export_json(change, comments))
    all_ = json.loads(export_json(change, comments, include_closed=True))
    md = export_markdown(change, comments)

    assert default["schema_version"] == "1.0.0"
    assert set(default["change"]) == {
        "id",
        "branch",
        "base_revision",
        "current_revision",
        "versions",
        "approval",
        "files",
    }
    assert default["change"]["current_revision"] == "rev-2"
    assert default["change"]["versions"] == ["rev-1", "rev-2"]
    assert default["change"]["files"] == [
        {"path": "new.txt", "additions": 3, "deletions": 0, "old_path": None}
    ]

    assert [c["id"] for c in default["comments"]] == ["c-root", "c-reply"]
    for comment in default["comments"]:
        assert comment["revision"] == "rev-2"
        assert "thread_id" not in comment
    assert default["comments"][1]["in_reply_to"] == "c-root"
    assert default["comments"][0]["in_reply_to"] is None

    assert [c["id"] for c in all_["comments"]] == ["c-root", "c-reply", "c-closed"]
    closed_block = all_["comments"][2]
    assert closed_block["state"] == "CLOSED"

    assert "## new.txt" in md
    assert "## src/foo.py" not in md
    assert "c-closed" not in md
