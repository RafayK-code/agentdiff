from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest
from tests.diff.conftest import load_fixture

from agentdiff.diff.parse import DiffParseError, parse_unified_diff
from agentdiff.diff.sources import (
    CommandRunner,
    GitDiffError,
    diff_from_git,
    diff_from_patch,
)

BASIC = load_fixture("basic.patch")


def _completed(
    args: Sequence[str], returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=list(args), returncode=returncode, stdout=stdout, stderr=stderr
    )


def _runner(stdout: str = "", returncode: int = 0, stderr: str = "") -> CommandRunner:
    def run(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return _completed(args, returncode=returncode, stdout=stdout, stderr=stderr)

    return run


@pytest.mark.parametrize(
    "base,head,expected_base,expected_head,expect_full_files",
    [
        ("abc123", "def456", "abc123", "def456", True),
        (None, None, None, None, False),
        ("HEAD", None, "HEAD", None, True),
    ],
    ids=["committed-range", "worktree", "head-only"],
)
def test_diff_from_git_revisions(
    base: str | None,
    head: str | None,
    expected_base: str | None,
    expected_head: str | None,
    expect_full_files: bool,
) -> None:
    change = diff_from_git(base=base, head=head, runner=_runner(stdout=BASIC))
    assert change.base_revision == expected_base
    assert change.head_revision == expected_head
    if expect_full_files:
        assert change.files == parse_unified_diff(BASIC).files
    else:
        assert change.files


@pytest.mark.parametrize(
    "base,head,runner,exc_type,message_fragment",
    [
        (
            "x",
            "y",
            _runner(returncode=128, stderr="fatal: bad revision"),
            GitDiffError,
            "fatal: bad revision",
        ),
        ("x", None, _runner(stdout=BASIC), ValueError, None),
        (None, "y", _runner(stdout=BASIC), ValueError, None),
        ("a", "b", _runner(), DiffParseError, None),
    ],
    ids=["nonzero-exit", "base-only", "head-only", "empty-stdout"],
)
def test_diff_from_git_errors(
    base: str | None,
    head: str | None,
    runner: CommandRunner,
    exc_type: type[Exception],
    message_fragment: str | None,
) -> None:
    with pytest.raises(exc_type) as excinfo:
        diff_from_git(base=base, head=head, runner=runner)
    if message_fragment is not None:
        assert message_fragment in str(excinfo.value)


@pytest.mark.parametrize(
    "kind",
    ["valid", "missing", "non-diff"],
    ids=["valid-file", "missing-file", "non-diff-content"],
)
def test_diff_from_patch(kind: str, tmp_path: Path) -> None:
    if kind == "valid":
        patch = tmp_path / "change.patch"
        patch.write_text(BASIC, encoding="utf-8")
        change = diff_from_patch(patch)
        assert change.files == parse_unified_diff(BASIC).files
        assert change.base_revision is None
        assert change.head_revision is None
    elif kind == "missing":
        with pytest.raises(FileNotFoundError):
            diff_from_patch(tmp_path / "does-not-exist.patch")
    else:
        patch = tmp_path / "junk.patch"
        patch.write_text("this is not a diff\n", encoding="utf-8")
        with pytest.raises(DiffParseError):
            diff_from_patch(patch)
