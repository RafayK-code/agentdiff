import pytest

from agentdiff import __version__
from agentdiff.cli import main


def test_version_flag_prints_version_and_exits_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = main(["--version"])
    captured = capsys.readouterr().out
    assert rc == 0
    assert captured.strip() == f"agentdiff {__version__}"
