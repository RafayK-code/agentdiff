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

    def line(change_id: str) -> str:
        return next(
            ln
            for ln in out.splitlines()
            if ln.startswith("  v")
            and ln.lstrip().startswith(("v1 ", "v2 "))
            and f" {change_id}  " in ln
        )

    assert line("chg-aaa").startswith("  v1 chg-aaa ")
    assert not line("chg-aaa").endswith("(tip)")
    assert "3f2a1b0→9c7d0e1" in line("chg-aaa")
    assert "2 comments" in line("chg-aaa")
    assert line("chg-bbb").startswith("  v2 chg-bbb ")
    assert line("chg-bbb").endswith("(tip)")
    assert "1 comment" in line("chg-bbb")
    assert line("chg-mmm").startswith("  v1 chg-mmm ")
    assert line("chg-mmm").endswith("(tip)")
    ppp = line("chg-ppp")
    assert "(none)→(none)" in ppp
    assert "0 comments" in ppp

    rc = main(["changes", "--branch", "feat/x", "--root", str(root)])
    captured = capsys.readouterr()
    out = captured.out
    assert rc == 0
    assert captured.err == ""
    assert out.index("v1 chg-aaa") < out.index("v2 chg-bbb")
    feat_x = next(ln for ln in out.splitlines() if ln.startswith("  v2 chg-bbb "))
    assert feat_x.endswith("(tip)")
    aaa = next(ln for ln in out.splitlines() if ln.startswith("  v1 chg-aaa "))
    assert not aaa.endswith("(tip)")
    for needle in ("chg-mmm", "chg-ppp", "(no branch)", "main"):
        assert needle not in out


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
