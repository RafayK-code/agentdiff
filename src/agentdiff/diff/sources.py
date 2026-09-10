from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from os import PathLike

from agentdiff.diff.parse import parse_unified_diff
from agentdiff.model.types import Change

CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]

_EMPTY_TREE_ARGV = ("git", "hash-object", "-t", "tree", "/dev/null")


class GitDiffError(RuntimeError):
    """A git command failed (nonzero exit); carries stderr + returncode."""

    def __init__(self, stderr: str, returncode: int) -> None:
        self.stderr = stderr
        self.returncode = returncode
        super().__init__(f"git command failed ({returncode}): {stderr}")


class NoCommitsError(GitDiffError):
    """HEAD is unborn: the repository has no commits to review."""

    def __init__(self) -> None:
        super().__init__("repository has no commits to review", 128)


def _default_runner(cwd: str | PathLike[str] | None) -> CommandRunner:
    def run(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run([*args], capture_output=True, text=True, cwd=cwd)

    return run


def _run(run: CommandRunner, argv: Sequence[str]) -> str:
    """Run argv; raise GitDiffError on nonzero exit; return stdout."""
    proc = run(list(argv))
    if proc.returncode != 0:
        raise GitDiffError(proc.stderr, proc.returncode)
    return proc.stdout


def _rev_parse(run: CommandRunner, rev: str) -> str:
    """Resolve rev to a commit SHA; GitDiffError (with git stderr) on failure."""
    return _run(run, ["git", "rev-parse", "--verify", f"{rev}^{{commit}}"]).strip()


def _head_sha(run: CommandRunner, head: str) -> str:
    """Resolve head to a commit SHA; NoCommitsError if head == 'HEAD' is unborn."""
    argv = ["git", "rev-parse", "--verify", "--quiet", f"{head}^{{commit}}"]
    proc = run(argv)
    if proc.returncode != 0:
        if head == "HEAD":
            raise NoCommitsError()
        raise GitDiffError(proc.stderr, proc.returncode)
    return proc.stdout.strip()


def _empty_tree(run: CommandRunner) -> str:
    """The repo's empty-tree object id (read-only hash-object)."""
    return _run(run, _EMPTY_TREE_ARGV).strip()


def _default_base_sha(run: CommandRunner, head_sha: str) -> str:
    """head_sha~1 if it resolves, else the empty-tree object id (root commit)."""
    argv = ["git", "rev-parse", "--verify", "--quiet", f"{head_sha}~1"]
    proc = run(argv)
    if proc.returncode != 0:
        return _empty_tree(run)
    return proc.stdout.strip()


def diff_from_git(
    base: str | None = None,
    head: str | None = None,
    *,
    runner: CommandRunner | None = None,
    cwd: str | PathLike[str] | None = None,
) -> Change:
    """Git source (R1): review a committed range as resolved SHAs."""
    run = runner if runner is not None else _default_runner(cwd)
    head_sha = _head_sha(run, head or "HEAD")
    if base is None:
        base_sha = _default_base_sha(run, head_sha)
    else:
        base_sha = _rev_parse(run, base)
    text = _run(run, ["git", "diff", base_sha, head_sha])
    change = parse_unified_diff(text)
    change.base_revision = base_sha
    change.head_revision = head_sha
    return change


def diff_from_patch(path: str | PathLike[str]) -> Change:
    """Patch source (R4): read a unified-diff .patch file and parse it.

    Revisions stay None. Caller errors (missing file) propagate.
    """
    with open(path, encoding="utf-8", errors="replace") as handle:
        text = handle.read()
    return parse_unified_diff(text)
