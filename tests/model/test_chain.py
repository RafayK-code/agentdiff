from __future__ import annotations

from tests.diff.conftest import load_fixture

from agentdiff.diff.parse import parse_unified_diff
from agentdiff.model import Change, Version


def test_change_versions_and_accessors() -> None:
    v1 = Version(
        revision="rev-1", files=parse_unified_diff(load_fixture("basic.patch")).files
    )
    v2 = Version(
        revision="rev-2", files=parse_unified_diff(load_fixture("new_file.patch")).files
    )
    change = Change(id="chg-s", versions=[v1, v2])
    empty = Change(id="chg-e")

    assert change.current is v2
    assert change.files == v2.files
    assert change.head_revision == "rev-2"
    assert change.version_for("rev-1") is v1
    assert change.version_for("nope") is None
    assert change.version_number("rev-1") == 1
    assert change.version_number("rev-2") == 2
    assert change.version_number("nope") is None
    assert change.version_at(1) is v1
    assert change.version_at(2) is v2
    assert change.version_at(0) is None
    assert change.version_at(3) is None

    assert empty.current is None
    assert empty.files == []
    assert empty.head_revision is None
    assert empty.version_at(1) is None
