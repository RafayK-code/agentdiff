from __future__ import annotations

import copy
import inspect
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.diff.conftest import load_fixture
from tests.export.conftest import comment_factory

from agentdiff.diff.parse import parse_unified_diff
from agentdiff.export import SCHEMA_VERSION, export_json
from agentdiff.model import Change, Comment, CommentState, LineRange, Side

RE_SEMVER = re.compile(r"\d+\.\d+\.\d+")
FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _single_file_doc(name: str) -> dict[str, object]:
    change = parse_unified_diff(load_fixture(name))
    files = json.loads(export_json(change, []))["change"]["files"]
    assert len(files) == 1
    return files[0]


# --- JSON API and schema version (R1, R5) ---


def test_api_signature() -> None:
    import agentdiff.export as export

    sig = inspect.signature(export.export_json)
    assert list(sig.parameters) == ["change", "comments"]
    assert all(
        p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
        for p in sig.parameters.values()
    )
    assert str(sig.parameters["change"].annotation) == "Change"
    assert str(sig.parameters["comments"].annotation) == "list[Comment]"
    assert str(sig.return_annotation) == "str"
    assert export.__all__ == ["SCHEMA_VERSION", "export_json", "export_markdown"]


def test_schema_version_constant() -> None:
    assert type(SCHEMA_VERSION) is str
    assert re.fullmatch(RE_SEMVER, SCHEMA_VERSION) is not None


def test_schema_version_in_output(
    approved_change, mixed_comments: list[Comment]
) -> None:
    doc = json.loads(export_json(approved_change, mixed_comments))
    assert doc["schema_version"] == SCHEMA_VERSION
    assert re.fullmatch(RE_SEMVER, doc["schema_version"]) is not None


def test_output_is_pure(approved_change, mixed_comments: list[Comment]) -> None:
    change_copy = copy.deepcopy(approved_change)
    comments_copy = copy.deepcopy(mixed_comments)
    out1 = export_json(approved_change, mixed_comments)
    out2 = export_json(approved_change, mixed_comments)
    assert out1 == out2
    assert approved_change == change_copy
    assert mixed_comments == comments_copy


# --- change block (R2) ---


def test_change_block_fields_and_order(
    approved_change, mixed_comments: list[Comment]
) -> None:
    parsed = json.loads(export_json(approved_change, mixed_comments))["change"]
    assert list(parsed.keys()) == [
        "id",
        "base_revision",
        "head_revision",
        "approval",
        "files",
    ]
    assert parsed["id"] == "chg-01"
    assert parsed["base_revision"] == "3f2a1b0"
    assert parsed["head_revision"] == "9c7d0e1"


def test_approval_present(approved_change, mixed_comments: list[Comment]) -> None:
    parsed = json.loads(export_json(approved_change, mixed_comments))["change"]
    assert parsed["approval"] == {
        "status": "APPROVED",
        "message": "LGTM, ship it",
        "author": "alice",
        "at": "2024-01-01T12:00:00Z",
    }


def test_approval_absent_is_null(
    unapproved_change, mixed_comments: list[Comment]
) -> None:
    out = export_json(unapproved_change, mixed_comments)
    parsed = json.loads(out)["change"]
    assert parsed["approval"] is None
    assert '"approval": null' in out


def test_file_block_order(approved_change, mixed_comments: list[Comment]) -> None:
    parsed = json.loads(export_json(approved_change, mixed_comments))
    for file in parsed["change"]["files"]:
        assert list(file.keys()) == ["path", "additions", "deletions", "old_path"]


def test_counts_basic() -> None:
    assert _single_file_doc("basic.patch") == {
        "path": "src/foo.py",
        "additions": 1,
        "deletions": 1,
        "old_path": None,
    }


def test_counts_multiple_hunks() -> None:
    file = _single_file_doc("multiple_hunks.patch")
    assert file["additions"] == 2
    assert file["deletions"] == 2


def test_counts_new_file() -> None:
    file = _single_file_doc("new_file.patch")
    assert file["additions"] == 3
    assert file["deletions"] == 0


def test_counts_deleted_file() -> None:
    file = _single_file_doc("deleted_file.patch")
    assert file["additions"] == 0
    assert file["deletions"] == 3


def test_counts_hunkless_files() -> None:
    for name in ("rename.patch", "mode_only.patch", "binary.patch"):
        file = _single_file_doc(name)
        assert file["additions"] == 0
        assert file["deletions"] == 0
    assert _single_file_doc("rename.patch") == {
        "path": "new.py",
        "additions": 0,
        "deletions": 0,
        "old_path": "old.py",
    }


def test_counts_ignore_context() -> None:
    change = parse_unified_diff(load_fixture("basic.patch"))
    out = export_json(change, [])
    files = json.loads(out)["change"]["files"]
    assert files[0]["additions"] == 1
    assert files[0]["deletions"] == 1
    assert "ctx1" not in out
    assert "ctx2" not in out


def test_old_path_set() -> None:
    assert _single_file_doc("rename_modify.patch") == {
        "path": "new.py",
        "additions": 1,
        "deletions": 1,
        "old_path": "old.py",
    }


def test_single_line_change() -> None:
    file = _single_file_doc("single_line.patch")
    assert file["additions"] == 1
    assert file["deletions"] == 1
    assert file["path"] == "s.txt"
    assert file["old_path"] is None


def test_empty_files_list() -> None:
    change = Change(id="chg-empty", files=[])
    parsed = json.loads(export_json(change, []))
    assert parsed["change"]["files"] == []
    assert parsed["comments"] == []


# --- comments block (R3) ---


def test_comment_fields_and_order(
    approved_change, mixed_comments: list[Comment]
) -> None:
    doc = json.loads(export_json(approved_change, mixed_comments))
    comment = next(c for c in doc["comments"] if c["id"] == "c-new")
    assert list(comment.keys()) == [
        "id",
        "file",
        "side",
        "lines",
        "text",
        "author",
        "thread_id",
        "state",
        "drifted",
        "created_at",
    ]
    assert comment["side"] == "NEW"
    assert comment["lines"] == [2, 2]
    assert comment["text"] == "Fix this"
    assert comment["author"] == "alice"
    assert comment["thread_id"] is None
    assert comment["state"] == "ACTIVE"
    assert comment["drifted"] is False
    assert comment["created_at"] == "2024-01-01T14:05:00Z"


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


def test_drifted_flag(approved_change, mixed_comments: list[Comment]) -> None:
    doc = json.loads(export_json(approved_change, mixed_comments))
    drifted = next(c for c in doc["comments"] if c["id"] == "c-drifted")
    assert drifted["state"] == "DRIFTED"
    assert drifted["drifted"] is True


def test_resolved_not_drifted(approved_change, mixed_comments: list[Comment]) -> None:
    doc = json.loads(export_json(approved_change, mixed_comments))
    resolved = next(c for c in doc["comments"] if c["id"] == "c-old-resolved")
    assert resolved["state"] == "RESOLVED"
    assert resolved["drifted"] is False


def test_drifted_derived_not_set(approved_change) -> None:
    comment = comment_factory(id="c-active", state=CommentState.ACTIVE)
    object.__setattr__(comment, "drifted", True)
    exported = json.loads(export_json(approved_change, [comment]))["comments"][0]
    assert exported["drifted"] is False


def test_thread_id_shared(approved_change, mixed_comments: list[Comment]) -> None:
    doc = json.loads(export_json(approved_change, mixed_comments))
    threaded = [c for c in doc["comments"] if c["id"] in ("c-thread-1", "c-thread-2")]
    assert [c["thread_id"] for c in threaded] == ["t-1", "t-1"]
    unthreaded = next(c for c in doc["comments"] if c["id"] == "c-new")
    assert unthreaded["thread_id"] is None


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


def test_created_at_utc_trailing_z(approved_change) -> None:
    comment = comment_factory(id="c-ts", created_at=datetime(2024, 1, 1, 14, 5, 30))
    exported = json.loads(export_json(approved_change, [comment]))["comments"][0]
    assert exported["created_at"] == "2024-01-01T14:05:30Z"


def test_created_at_aware_converted(approved_change) -> None:
    aware = datetime(2024, 1, 1, 9, 5, 30, tzinfo=timezone(timedelta(hours=-5)))
    comment = comment_factory(id="c-aware", created_at=aware)
    exported = json.loads(export_json(approved_change, [comment]))["comments"][0]
    assert exported["created_at"] == "2024-01-01T14:05:30Z"


def test_created_at_microseconds_truncated(approved_change) -> None:
    comment = comment_factory(
        id="c-micro", created_at=datetime(2024, 1, 1, 14, 5, 30, 123456)
    )
    exported = json.loads(export_json(approved_change, [comment]))["comments"][0]
    assert exported["created_at"] == "2024-01-01T14:05:30Z"


def test_unicode_escaped_ascii(approved_change) -> None:
    comment = comment_factory(id="c-u", text="café ☕", author="joán")
    out = export_json(approved_change, [comment])
    assert '"caf\\u00e9 \\u2615"' in out
    assert '"jo\\u00e1n"' in out
    exported = json.loads(out)["comments"][0]
    assert exported["text"] == "café ☕"
    assert exported["author"] == "joán"


# --- Golden fixture (R7) ---


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


def test_golden_has_file_level_and_thread_mix(
    approved_change, mixed_comments: list[Comment]
) -> None:
    comments = json.loads(export_json(approved_change, mixed_comments))["comments"]
    file_level_drifted = [
        c
        for c in comments
        if c["side"] is None
        and c["lines"] is None
        and c["state"] == "DRIFTED"
        and c["drifted"] is True
    ]
    assert len(file_level_drifted) == 1
    assert sum(1 for c in comments if c["thread_id"] == "t-1") >= 2
    assert any(c["state"] == "RESOLVED" and c["drifted"] is False for c in comments)
    assert any(c["side"] == "NEW" for c in comments)
