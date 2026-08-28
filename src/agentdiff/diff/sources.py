from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from os import PathLike

from agentdiff.diff.parse import parse_unified_diff
from agentdiff.model.types import Change

CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


class GitDiffError(RuntimeError):
    """The `git diff` invocation failed (nonzero exit).

    Carries the captured stderr text from git.
    """

    def __init__(self, stderr: str, returncode: int) -> None:
        self.stderr = stderr
        self.returncode = returncode
        super().__init__(f"git diff failed ({returncode}): {stderr}")


def _default_runner(cwd: str | PathLike[str] | None) -> CommandRunner:
    def run(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run([*args], capture_output=True, text=True, cwd=cwd)

    return run


def diff_from_git(
    base: str | None = None,
    head: str | None = None,
    *,
    runner: CommandRunner | None = None,
    cwd: str | PathLike[str] | None = None,
) -> Change:
    """Git source (R3): build `git diff` argv, run it, parse, set revisions."""
    if base is None and head is not None:
        raise ValueError("a head revision requires a base revision")
    if base is not None and head is None and base != "HEAD":
        raise ValueError("a single revision must be 'HEAD' (diff against the worktree)")
    argv = ["git", "diff"]
    if base is not None:
        argv.append(base)
    if head is not None:
        argv.append(head)
    run = runner if runner is not None else _default_runner(cwd)
    proc = run(argv)
    if proc.returncode != 0:
        raise GitDiffError(proc.stderr, proc.returncode)
    change = parse_unified_diff(proc.stdout)
    change.base_revision = base
    change.head_revision = head
    return change


def diff_from_patch(path: str | PathLike[str]) -> Change:
    """Patch source (R4): read a unified-diff .patch file and parse it.

    Revisions stay None. Caller errors (missing file) propagate.
    """
    with open(path, encoding="utf-8", errors="replace") as handle:
        text = handle.read()
    return parse_unified_diff(text)
