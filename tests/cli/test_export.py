from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.store.conftest import CanonicalStore

from agentdiff.cli import main
from agentdiff.export import export_json, export_markdown


def test_export_change_checkout_independent_and_locked_readable(
    capsys: pytest.CaptureFixture[str],
    canonical_store: CanonicalStore,
    decoy_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = canonical_store.store
    monkeypatch.chdir(decoy_root)
    rc = main(
        [
            "export",
            "--change",
            "chg-aaa",
            "--format",
            "json",
            "--root",
            str(canonical_store.root),
        ]
    )
    captured = capsys.readouterr()
    expected = export_json(store.load_change("chg-aaa"), store.list_comments("chg-aaa"))
    assert rc == 0
    assert captured.out == expected
    assert captured.err == ""


def test_export_branch_yields_tip_only(
    capsys: pytest.CaptureFixture[str], canonical_store: CanonicalStore
) -> None:
    rc = main(
        [
            "export",
            "--branch",
            "feat/x",
            "--format",
            "json",
            "--root",
            str(canonical_store.root),
        ]
    )
    captured = capsys.readouterr()
    doc = json.loads(captured.out)
    assert rc == 0
    assert captured.err == ""
    assert doc["change"]["id"] == "chg-bbb"
    assert doc["change"]["prev_change"] == "chg-aaa"
    assert [c["id"] for c in doc["comments"]] == ["c-3"]
    for comment in doc["comments"]:
        assert comment["id"] not in ("c-1", "c-2")


def test_export_hides_closed_both_formats(
    capsys: pytest.CaptureFixture[str], canonical_store: CanonicalStore
) -> None:
    root = canonical_store.root

    def run(argv: list[str]) -> str:
        rc = main([*argv, "--root", str(root)])
        captured = capsys.readouterr()
        assert rc == 0
        assert captured.err == ""
        return captured.out

    default_json = run(["export", "--change", "chg-bbb", "--format", "json"])
    assert [c["id"] for c in json.loads(default_json)["comments"]] == ["c-3"]

    all_json = run(
        ["export", "--change", "chg-bbb", "--format", "json", "--include-closed"]
    )
    doc = json.loads(all_json)
    assert [c["id"] for c in doc["comments"]] == ["c-3", "c-4"]
    closed = next(c for c in doc["comments"] if c["id"] == "c-4")
    assert closed["state"] == "CLOSED"

    default_md = run(["export", "--change", "chg-bbb"])
    assert "c-4:" not in default_md
    all_md = run(["export", "--change", "chg-bbb", "--include-closed"])
    assert "c-4:" in all_md

    branch_json = run(
        ["export", "--branch", "feat/x", "--format", "json", "--include-closed"]
    )
    assert [c["id"] for c in json.loads(branch_json)["comments"]] == ["c-3", "c-4"]


def test_export_error_contract(
    capsys: pytest.CaptureFixture[str], canonical_store: CanonicalStore
) -> None:
    root = canonical_store.root
    variants = [
        ["export", "--root", str(root)],
        ["export", "--change", "chg-aaa", "--branch", "feat/x", "--root", str(root)],
        ["export", "--change", "chg-nope", "--root", str(root)],
        ["export", "--branch", "bogus", "--root", str(root)],
        ["export", "--change", "chg-nope", "--format", "yaml", "--root", str(root)],
    ]
    for i, argv in enumerate(variants):
        rc = main(argv)
        captured = capsys.readouterr()
        assert rc == 1
        assert captured.out == ""
        assert captured.err.startswith("agentdiff: "), argv
        if i in (0, 1):
            assert "exactly one" in captured.err
        elif i == 2:
            assert "chg-nope" in captured.err
        elif i == 3:
            assert "bogus" in captured.err
        else:
            assert "yaml" in captured.err
            assert "json" in captured.err
            assert "markdown" in captured.err
            assert "chg-nope" not in captured.err


def test_export_format_and_out(
    capsys: pytest.CaptureFixture[str],
    canonical_store: CanonicalStore,
    tmp_path: Path,
) -> None:
    store = canonical_store.store
    root = canonical_store.root

    rc = main(["export", "--change", "chg-bbb", "--root", str(root)])
    captured = capsys.readouterr()
    expected_md = export_markdown(
        store.load_change("chg-bbb"), store.list_comments("chg-bbb")
    )
    assert rc == 0
    assert captured.out == expected_md
    assert captured.out.startswith("# Change chg-bbb")
    assert captured.err == ""

    rc = main(
        ["export", "--change", "chg-bbb", "--format", "json", "--root", str(root)]
    )
    captured = capsys.readouterr()
    expected_json = export_json(
        store.load_change("chg-bbb"), store.list_comments("chg-bbb")
    )
    assert rc == 0
    assert captured.out == expected_json
    assert captured.err == ""
    json.loads(captured.out)

    out_path = tmp_path / "out.json"
    rc = main(
        [
            "export",
            "--change",
            "chg-mmm",
            "--format",
            "json",
            "--out",
            str(out_path),
            "--root",
            str(root),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0
    assert out_path.read_text(encoding="utf-8") == export_json(
        store.load_change("chg-mmm"), store.list_comments("chg-mmm")
    )
    assert captured.out == ""
    assert captured.err == ""

    rc = main(
        [
            "export",
            "--change",
            "chg-mmm",
            "--format",
            "json",
            "--out",
            str(tmp_path / "no-such-dir" / "x.json"),
            "--root",
            str(root),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == ""
    assert captured.err.startswith("agentdiff: ")
