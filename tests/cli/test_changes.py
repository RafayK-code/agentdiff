from __future__ import annotations

from pathlib import Path

import pytest
from tests.store.conftest import CanonicalStore

from agentdiff.cli import main


def test_changes_listing_and_branch_filter(
    capsys: pytest.CaptureFixture[str],
    canonical_store: CanonicalStore,
) -> None:
    root = canonical_store.root

    rc = main(["changes", "--root", str(root)])
    captured = capsys.readouterr()
    out = captured.out
    assert rc == 0
    assert captured.err == ""
    assert out.index("(no branch)") < out.index("feat/x") < out.index("main")
    for change_id in ("chg-aaa", "chg-bbb", "chg-mmm", "chg-ppp"):
        assert change_id in out
    for revision in ("9c7d0e1", "d4e5f6a", "1234567", "ppp0001"):
        assert revision in out

    def line(change_id: str) -> str:
        return next(ln for ln in out.splitlines() if f" {change_id} " in ln)

    assert "versions=1" in line("chg-aaa")
    assert "2 comments" in line("chg-aaa")
    assert "versions=1" in line("chg-bbb")
    assert "1 comment" in line("chg-bbb")
    assert "(none)" in line("chg-ppp")
    assert "0 comments" in line("chg-ppp")

    rc = main(["changes", "--branch", "feat/x", "--root", str(root)])
    captured = capsys.readouterr()
    out = captured.out
    assert rc == 0
    assert captured.err == ""
    assert "chg-aaa" in out and "chg-bbb" in out
    for needle in ("chg-mmm", "chg-ppp", "(no branch)", "main"):
        assert needle not in out


def test_changes_hides_closed(
    capsys: pytest.CaptureFixture[str],
    canonical_store: CanonicalStore,
) -> None:
    root = canonical_store.root

    rc = main(["changes", "--root", str(root)])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.err == ""
    default_line = next(ln for ln in captured.out.splitlines() if "chg-bbb" in ln)
    assert "1 comment" in default_line

    rc = main(["changes", "--root", str(root), "--include-closed"])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.err == ""
    closed_line = next(ln for ln in captured.out.splitlines() if "chg-bbb" in ln)
    assert "2 comments" in closed_line


def test_changes_empty_inputs(
    capsys: pytest.CaptureFixture[str],
    canonical_store: CanonicalStore,
    tmp_path: Path,
) -> None:
    store_root = canonical_store.root
    fresh_root = tmp_path / "fresh"
    variants = [
        ["changes", "--root", str(fresh_root)],
        ["changes", "--root", str(store_root / "does-not-exist")],
        ["changes", "--branch", "bogus", "--root", str(store_root)],
    ]
    for argv in variants:
        rc = main(argv)
        captured = capsys.readouterr()
        assert rc == 0
        assert captured.out == "No changes.\n"
        assert captured.err == ""


def test_changes_bad_root_error(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    a_file = tmp_path / "a-file"
    a_file.write_text("x", encoding="utf-8")
    rc = main(["changes", "--root", str(a_file)])
    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == ""
    assert captured.err.startswith("agentdiff: ")
    assert "not a directory" in captured.err


def test_changes_lookup_by_revision(
    capsys: pytest.CaptureFixture[str],
    canonical_store: CanonicalStore,
) -> None:
    root = canonical_store.root
    expected = {"9c7d0e1": "chg-aaa", "d4e5f6a": "chg-bbb"}
    for revision, change_id in expected.items():
        for flag in ("--revision", "--commit"):
            rc = main(["changes", flag, revision, "--root", str(root)])
            captured = capsys.readouterr()
            assert rc == 0
            assert captured.err == ""
            assert captured.out == f"{change_id}\n"


def test_changes_lookup_by_revision_unknown(
    capsys: pytest.CaptureFixture[str],
    canonical_store: CanonicalStore,
) -> None:
    rc = main(
        ["changes", "--revision", "deadbeef", "--root", str(canonical_store.root)]
    )
    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == ""
    assert "no change contains revision" in captured.err
