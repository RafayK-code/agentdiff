from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from os import PathLike

from agentdiff.diff.parse import parse_unified_diff
from agentdiff.model.types import Change, stable_change_id

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


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


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
    """Git source (R3, R4): review a committed range as resolved SHAs.

    Stamps the stable ``id``/``branch``/``base_revision`` and the version's head
    revision and creation time; this is the ingest entry point.
    """
    run = runner if runner is not None else _default_runner(cwd)
    head_sha = _head_sha(run, head or "HEAD")
    if base is None:
        base_sha = _default_base_sha(run, head_sha)
    else:
        base_sha = _rev_parse(run, base)
    branch = current_branch(runner=run, cwd=cwd)
    text = _run(run, ["git", "diff", base_sha, head_sha])
    change = parse_unified_diff(text)
    change.id = stable_change_id(branch, base_sha)
    change.branch = branch
    change.base_revision = base_sha
    change.versions[0].revision = head_sha
    change.created_at = change.versions[0].created_at = _now_utc()
    return change


def current_branch(
    *,
    runner: CommandRunner | None = None,
    cwd: str | PathLike[str] | None = None,
) -> str | None:
    """git symbolic-ref --short -q HEAD; None on detached HEAD or error."""
    run = runner if runner is not None else _default_runner(cwd)
    proc = run(["git", "symbolic-ref", "--short", "-q", "HEAD"])
    if proc.returncode != 0:
        return None
    name = proc.stdout.strip()
    return name or None


def head_commit_title(
    *,
    runner: CommandRunner | None = None,
    cwd: str | PathLike[str] | None = None,
) -> str | None:
    """The HEAD commit subject (git log -1 --format=%s); None on error."""
    run = runner if runner is not None else _default_runner(cwd)
    proc = run(["git", "log", "-1", "--format=%s", "HEAD"])
    if proc.returncode != 0:
        return None
    title = proc.stdout.strip()
    return title or None


def read_file_at_revision(
    revision: str,
    path: str,
    *,
    runner: CommandRunner | None = None,
    cwd: str | PathLike[str] | None = None,
) -> str | None:
    """File text at revision via `git show <rev>:<path>`.

    Read-only (side-effect-free); injectable-runner pattern like the other
    sources. A nonzero exit (path absent at revision) returns None; it does not
    raise. OSError from the runner propagates and is mapped by the caller.
    """
    run = runner if runner is not None else _default_runner(cwd)
    proc = run(["git", "show", f"{revision}:{path}"])
    if proc.returncode != 0:
        return None
    return proc.stdout


def diff_from_patch(path: str | PathLike[str]) -> Change:
    """Patch source (R4): read a unified-diff .patch file and parse it.

    Revisions stay None. Caller errors (missing file) propagate.
    """
    with open(path, encoding="utf-8", errors="replace") as handle:
        text = handle.read()
    return parse_unified_diff(text)
