from __future__ import annotations

import io
from pathlib import Path

import pytest
from tests.cli.conftest import FakeTTY

from agentdiff.cli import main


def test_bare_tty_launches_tui_with_default_root() -> None:
    out = FakeTTY()
    err = io.StringIO()
    calls: list[Path] = []

    def launch(root: Path) -> int:
        calls.append(root)
        return 0

    rc = main([], stdout=out, stderr=err, launch=launch)

    assert rc == 0
    assert calls == [Path(".")]
    assert err.getvalue() == ""


def test_bare_tty_launches_tui_with_root(tmp_path: Path) -> None:
    out = FakeTTY()
    err = io.StringIO()
    calls: list[Path] = []

    def launch(root: Path) -> int:
        calls.append(root)
        return 0

    rc = main(["--root", str(tmp_path)], stdout=out, stderr=err, launch=launch)

    assert rc == 0
    assert calls == [tmp_path]
    assert err.getvalue() == ""


def test_bare_piped_prints_usage(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main([])
    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == ""
    assert "usage: agentdiff" in captured.err
