from __future__ import annotations

from tests.diff.conftest import load_fixture
from tests.tui.conftest import comment_factory, make_version

from agentdiff.diff.parse import parse_unified_diff
from agentdiff.model import Change
from agentdiff.tui.state import (
    FileStatus,
    build_shell_state,
    empty_state,
    format_header,
    is_current_version,
    select_file,
    select_version,
    selected_version,
    summarize_file,
)


def test_version_defaults_navigation_and_header() -> None:
    v1 = make_version("rev-1", "basic.patch")
    v2 = make_version("rev-2", "basic.patch", "new_file.patch")
    change = Change(id="chg-s", branch="feat/x", versions=[v1, v2])
    c = comment_factory("c-1", revision="rev-2")

    state = build_shell_state(change, commit_title="Add foo", comments=(c,))
    moved = select_file(state, +1)
    prev = select_version(moved, -1)
    back = select_version(prev, -1)
    fwd = select_version(state, +1)
    single = build_shell_state(Change(id="chg-1", versions=[v1]))
    none = empty_state()

    assert state.version_index == 1
    assert selected_version(state) is change.versions[1]
    assert is_current_version(state) is True
    assert state.comments == (c,)
    assert "v2 of 2" in format_header(state)
    assert "(history)" not in format_header(state)
    assert moved.selected == 1
    assert prev.version_index == 0
    assert selected_version(prev) is change.versions[0]
    assert is_current_version(prev) is False
    assert prev.selected == 0
    assert [e.path for e in prev.files] == ["src/foo.py"]
    assert "v1 of 2" in format_header(prev)
    assert "(history)" in format_header(prev)
    assert back.version_index == 0
    assert fwd.version_index == 1
    assert single.version_index == 0
    assert "v1 of 1" in format_header(single)
    assert format_header(none) == "agentdiff"


def test_select_version_clamps_rebuilds_and_resets_cursor() -> None:
    v1 = make_version("rev-1", "basic.patch")
    v2 = make_version("rev-2", "basic.patch", "new_file.patch")
    change = Change(id="chg-s", versions=[v1, v2])
    state = build_shell_state(change)

    moved = select_file(state, +1)
    prev = select_version(moved, -1)
    prev_prev = select_version(prev, -1)
    next_ = select_version(state, +1)
    forward = select_version(prev, +1)

    assert state.version_index == 1 and moved.selected == 1
    assert prev.version_index == 0
    assert selected_version(prev) is change.versions[0]
    assert is_current_version(prev) is False
    assert prev.selected == 0
    assert [e.path for e in prev.files] == ["src/foo.py"]
    assert "v1 of 2" in format_header(prev)
    assert "(history)" in format_header(prev)
    assert prev_prev.version_index == 0
    assert next_.version_index == 1
    assert forward.version_index == 1 and is_current_version(forward) is True


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
