from __future__ import annotations

import pytest
from tests.diff.conftest import load_fixture
from tests.diff.test_parse import _WELL_FORMED_FIXTURE_NAMES

from agentdiff.diff.parse import parse_unified_diff
from agentdiff.diff.serialize import serialize_unified_diff
from agentdiff.model.types import Change, FileDiff, Hunk, Line


def test_r7_roundtrip_basic() -> None:
    change = parse_unified_diff(load_fixture("basic.patch"))
    reparsed = parse_unified_diff(serialize_unified_diff(change))
    assert reparsed.files == change.files


@pytest.mark.parametrize("name", ["rename.patch", "mode_only.patch"])
def test_r7_canonical_id_stable(name: str) -> None:
    change = parse_unified_diff(load_fixture(name))
    reparsed = parse_unified_diff(serialize_unified_diff(change))
    assert reparsed.files == change.files
    assert reparsed.id == change.id


@pytest.mark.parametrize("name", _WELL_FORMED_FIXTURE_NAMES)
def test_r7_roundtrip_all_edge_fixtures(name: str) -> None:
    change = parse_unified_diff(load_fixture(name))
    reparsed = parse_unified_diff(serialize_unified_diff(change))
    assert reparsed.files == change.files


def test_r7_serializer_emits_new_file_mode() -> None:
    change = parse_unified_diff(load_fixture("new_file.patch"))
    out = serialize_unified_diff(change)
    assert "new file mode 100644" in out
    assert "--- /dev/null" in out
    assert parse_unified_diff(out).files == change.files


def test_r7_serializer_emits_deleted_file_mode() -> None:
    change = parse_unified_diff(load_fixture("deleted_file.patch"))
    out = serialize_unified_diff(change)
    assert "deleted file mode 100644" in out
    assert "+++ /dev/null" in out
    assert parse_unified_diff(out).files == change.files


def test_r7_serializer_mode_only_not_rename() -> None:
    change = parse_unified_diff(load_fixture("mode_only.patch"))
    out = serialize_unified_diff(change)
    assert "old mode 100644" in out
    assert "new mode 100755" in out
    assert "rename" not in out
    assert parse_unified_diff(out).files == change.files


def test_r7_serializer_rename_lines() -> None:
    change = parse_unified_diff(load_fixture("rename.patch"))
    out = serialize_unified_diff(change)
    assert "rename from old.py" in out
    assert "rename to new.py" in out
    assert parse_unified_diff(out).files == change.files


def test_r7_serializer_binary_line() -> None:
    change = parse_unified_diff(load_fixture("binary.patch"))
    out = serialize_unified_diff(change)
    assert "Binary files a/img.bin and b/img.bin differ" in out
    assert parse_unified_diff(out).files == change.files


def test_r7_serializer_recomputes_counts() -> None:
    hunk = Hunk.model_construct(
        old_start=1,
        old_count=1,
        new_start=1,
        new_count=1,
        lines=[Line(kind="add", old_no=None, new_no=1, text="a")],
    )
    change = Change.model_construct(
        id="x", files=[FileDiff.model_construct(path="x", hunks=[hunk])]
    )
    out = serialize_unified_diff(change)
    reparsed = parse_unified_diff(out)
    assert reparsed.files[0].hunks[0].old_count == 0
    assert reparsed.files[0].hunks[0].new_count == 1
