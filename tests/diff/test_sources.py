from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from tests.diff.conftest import load_fixture

from agentdiff.diff.parse import DiffParseError, parse_unified_diff
from agentdiff.diff.sources import (
    CommandRunner,
    GitDiffError,
    diff_from_git,
    diff_from_patch,
)
from agentdiff.model.types import Change

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


class FakeRunner:
    def __init__(self, stdout: str = "", returncode: int = 0, stderr: str = "") -> None:
        self.calls: list[list[str]] = []
        self._stdout = stdout
        self._returncode = returncode
        self._stderr = stderr

    def run(self, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(args))
        return _completed(args, self._returncode, self._stdout, self._stderr)


def test_r3_committed_range_revisions() -> None:
    fake = _runner(stdout=BASIC)
    change = diff_from_git(base="abc123", head="def456", runner=fake)
    assert change.base_revision == "abc123"
    assert change.head_revision == "def456"
    assert change.files == parse_unified_diff(BASIC).files


def test_r3_committed_range_argv() -> None:
    rec = FakeRunner(stdout=BASIC)
    diff_from_git(base="abc123", head="def456", runner=rec.run)
    assert rec.calls == [["git", "diff", "abc123", "def456"]]


def test_r3_worktree_diff() -> None:
    fake = _runner(stdout=BASIC)
    change = diff_from_git(runner=fake)
    assert change.base_revision is None
    assert change.head_revision is None
    assert change.files


def test_r3_worktree_argv() -> None:
    rec = FakeRunner(stdout=BASIC)
    diff_from_git(runner=rec.run)
    assert rec.calls == [["git", "diff"]]


def test_r3_head_only() -> None:
    rec = FakeRunner(stdout=BASIC)
    change = diff_from_git(base="HEAD", runner=rec.run)
    assert rec.calls == [["git", "diff", "HEAD"]]
    assert change.base_revision == "HEAD"
    assert change.head_revision is None


def test_r3_error_nonzero_exit() -> None:
    fake_bad = _runner(returncode=128, stderr="fatal: bad revision")
    with pytest.raises(GitDiffError) as excinfo:
        diff_from_git(base="x", head="y", runner=fake_bad)
    assert "fatal: bad revision" in str(excinfo.value)


def test_r3_error_half_arguments() -> None:
    fake = _runner(stdout=BASIC)
    with pytest.raises(ValueError):
        diff_from_git(base="abc123", runner=fake)
    with pytest.raises(ValueError):
        diff_from_git(head="def456", runner=fake)


def test_r3_empty_stdout_parse_error() -> None:
    fake_empty = _runner()
    with pytest.raises(DiffParseError):
        diff_from_git(base="a", head="b", runner=fake_empty)


def test_r3_default_runner_is_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _init_repo(tmp_path / "repo", changed=True)
    real_run = subprocess.run
    seen: dict[str, Any] = {}

    def spy(args: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen["kwargs"] = kwargs
        return real_run(args, **kwargs)

    monkeypatch.setattr("agentdiff.diff.sources.subprocess.run", spy)
    change = diff_from_git(base="HEAD", cwd=repo)
    assert seen["kwargs"].get("capture_output") is True
    assert seen["kwargs"].get("text") is True
    assert isinstance(change, Change)
    assert change.base_revision == "HEAD"


def test_r4_patch_file(tmp_path: Path) -> None:
    patch = tmp_path / "change.patch"
    patch.write_text(BASIC, encoding="utf-8")
    change = diff_from_patch(patch)
    assert change.files == parse_unified_diff(BASIC).files
    assert change.base_revision is None
    assert change.head_revision is None


def test_r4_patch_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        diff_from_patch(tmp_path / "does-not-exist.patch")


def test_r4_patch_non_diff_content(tmp_path: Path) -> None:
    patch = tmp_path / "junk.patch"
    patch.write_text("this is not a diff\n", encoding="utf-8")
    with pytest.raises(DiffParseError):
        diff_from_patch(patch)


def _init_repo(repo: Path, changed: bool) -> Path:
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "T")
    _git(repo, "config", "user.email", "t@e.c")
    (repo / "data.txt").write_text("line1\nline2\nline3\n", encoding="utf-8")
    _git(repo, "add", "data.txt")
    _git(repo, "commit", "-qm", "base")
    if changed:
        (repo / "data.txt").write_text(
            "line1\nline2\nline3-changed\n", encoding="utf-8"
        )
    return repo


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
