from __future__ import annotations

import pytest
from tests.diff.conftest import load_fixture
from tests.diff.test_parse import _WELL_FORMED_FIXTURE_NAMES

from agentdiff.diff.parse import parse_unified_diff
from agentdiff.diff.serialize import serialize_file, serialize_unified_diff
from agentdiff.model.types import Change, FileDiff, Hunk, Line, Version


@pytest.mark.parametrize("name", _WELL_FORMED_FIXTURE_NAMES)
def test_serialize_roundtrip(name: str) -> None:
    change = parse_unified_diff(load_fixture(name))
    reparsed = parse_unified_diff(serialize_unified_diff(change))
    assert reparsed.files == change.files


@pytest.mark.parametrize("name", ["rename.patch", "mode_only.patch"])
def test_serialize_keeps_change_id(name: str) -> None:
    change = parse_unified_diff(load_fixture(name))
    reparsed = parse_unified_diff(serialize_unified_diff(change))
    assert reparsed.files == change.files
    assert reparsed.id == change.id


@pytest.mark.parametrize(
    "name,expected_substrings,absent_substrings",
    [
        ("new_file.patch", ["new file mode 100644", "--- /dev/null"], []),
        ("deleted_file.patch", ["deleted file mode 100644", "+++ /dev/null"], []),
        (
            "mode_only.patch",
            ["old mode 100644", "new mode 100755"],
            ["rename"],
        ),
        ("rename.patch", ["rename from old.py", "rename to new.py"], []),
        ("binary.patch", ["Binary files a/img.bin and b/img.bin differ"], []),
    ],
    ids=[
        "new-file-mode",
        "deleted-file-mode",
        "mode-only-not-rename",
        "rename-lines",
        "binary-line",
    ],
)
def test_serialize_emits_modes_and_headers(
    name: str,
    expected_substrings: list[str],
    absent_substrings: list[str],
) -> None:
    change = parse_unified_diff(load_fixture(name))
    out = serialize_unified_diff(change)
    for substring in expected_substrings:
        assert substring in out
    for substring in absent_substrings:
        assert substring not in out
    assert parse_unified_diff(out).files == change.files


def test_serialize_file_canonical_and_limited_to_hunks() -> None:
    file = parse_unified_diff(load_fixture("multiple_hunks.patch")).files[0]
    full = serialize_file(file)
    second = serialize_file(file, file.hunks[1:])
    one = Change(id="chg-s", versions=[Version(revision="rev-1", files=[file])])

    assert full == serialize_unified_diff(one)
    assert "@@ -1,6 +1,6 @@" in full
    assert "@@ -19,7 +19,7 @@" in full
    assert "@@ -19,7 +19,7 @@" in second
    assert "@@ -1,6 +1,6 @@" not in second
    assert parse_unified_diff(full).files == [file]


def test_serialize_recomputes_hunk_counts() -> None:
    hunk = Hunk.model_construct(
        old_start=1,
        old_count=1,
        new_start=1,
        new_count=1,
        lines=[Line(kind="add", old_no=None, new_no=1, text="a")],
    )
    change = Change.model_construct(
        id="x",
        versions=[
            Version.model_construct(
                revision="r", files=[FileDiff.model_construct(path="x", hunks=[hunk])]
            )
        ],
    )
    out = serialize_unified_diff(change)
    reparsed = parse_unified_diff(out)
    assert reparsed.files[0].hunks[0].old_count == 0
    assert reparsed.files[0].hunks[0].new_count == 1
