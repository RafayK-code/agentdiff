from __future__ import annotations

import pytest
from tests.diff.conftest import load_fixture
from tests.store.conftest import CanonicalStore

from agentdiff.cli import main
from agentdiff.cli.show import hunks_for
from agentdiff.diff.parse import parse_unified_diff
from agentdiff.model import LineRange, Side


def test_hunks_for_selects_overlapping_hunk() -> None:
    file = parse_unified_diff(load_fixture("multiple_hunks.patch")).files[0]

    assert hunks_for(file, LineRange(side=Side.NEW, start=22, end=22)) == (
        file.hunks[1],
    )
    assert hunks_for(file, LineRange(side=Side.NEW, start=3, end=3)) == (file.hunks[0],)
    assert hunks_for(file, LineRange(side=Side.OLD, start=22, end=22)) == (
        file.hunks[1],
    )
    assert hunks_for(file, None) == tuple(file.hunks)
    assert hunks_for(file, LineRange(side=Side.NEW, start=10, end=10)) == tuple(
        file.hunks
    )


def test_show_prints_comment_side_and_hunk_context(
    capsys: pytest.CaptureFixture[str], canonical_store: CanonicalStore
) -> None:
    rc = main(["show", "c-3", "--root", str(canonical_store.root)])
    out = capsys.readouterr()

    assert rc == 0
    assert out.err == ""
    assert out.out.strip() != ""
    assert "c-3" in out.out
    assert "NEW" in out.out
    assert "@@ -1,3 +1,3 @@" in out.out
    assert "-removed" in out.out and "+added" in out.out


def test_show_unknown_comment_id_exits_1(
    capsys: pytest.CaptureFixture[str], canonical_store: CanonicalStore
) -> None:
    rc = main(["show", "c-nope", "--root", str(canonical_store.root)])
    out = capsys.readouterr()

    assert rc == 1
    assert out.out == ""
    assert out.err.startswith("agentdiff: ")
    assert "c-nope" in out.err
