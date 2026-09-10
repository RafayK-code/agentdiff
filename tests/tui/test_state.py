from __future__ import annotations

from tests.diff.conftest import load_fixture

from agentdiff.diff.parse import parse_unified_diff
from agentdiff.tui.state import FileStatus, summarize_file


def test_summarize_file_status_and_counts() -> None:
    cases = {
        "basic.patch": ("src/foo.py", FileStatus.MODIFIED, None, 1, 1),
        "new_file.patch": ("new.txt", FileStatus.ADDED, None, 3, 0),
        "deleted_file.patch": ("old.txt", FileStatus.DELETED, None, 0, 3),
        "rename.patch": ("new.py", FileStatus.RENAMED, "old.py", 0, 0),
        "binary.patch": ("img.bin", FileStatus.BINARY, None, 0, 0),
        "multiple_hunks.patch": ("m.txt", FileStatus.MODIFIED, None, 2, 2),
    }

    for fixture, expected in cases.items():
        file = parse_unified_diff(load_fixture(fixture)).files[0]
        entry = summarize_file(file)
        actual = (
            entry.path,
            entry.status,
            entry.old_path,
            entry.additions,
            entry.deletions,
        )
        assert actual == expected, fixture
