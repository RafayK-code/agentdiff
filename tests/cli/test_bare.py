from __future__ import annotations

import io

import pytest
from tests.cli.conftest import FakeTTY

from agentdiff.cli import TUI_PENDING_MESSAGE, main


def test_bare_tty_prints_pending_message() -> None:
    out = FakeTTY()
    err = io.StringIO()
    rc = main([], stdout=out, stderr=err)
    assert rc == 0
    assert out.getvalue() == TUI_PENDING_MESSAGE + "\n"
    assert err.getvalue() == ""


def test_bare_piped_prints_usage(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main([])
    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == ""
    assert "usage: agentdiff" in captured.err
