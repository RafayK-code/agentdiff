from __future__ import annotations

from pathlib import Path

from agentdiff.diff import (
    CommandRunner,
    DiffParseError,
    GitDiffError,
    NoCommitsError,
    current_branch,
    diff_from_git,
    head_commit_title,
)
from agentdiff.store import Store, StoreError, create_store
from agentdiff.tui.state import ShellState, build_shell_state, empty_state, error_state


def load_shell_state(
    root: Path,
    *,
    runner: CommandRunner | None = None,
    store: Store | None = None,
) -> ShellState:
    """Run the R4 load pipeline, mapping expected failures to empty/error states."""
    try:
        change = diff_from_git(runner=runner, cwd=root)
    except NoCommitsError:
        return error_state("Repository has no commits to review.")
    except DiffParseError:
        return empty_state()
    except (GitDiffError, OSError) as exc:
        return error_state(f"git error: {exc}")

    change.branch = current_branch(runner=runner, cwd=root)
    title = head_commit_title(runner=runner, cwd=root)
    try:
        (store if store is not None else create_store(root)).save_change(change)
    except StoreError as exc:
        return error_state(f"store error: {exc}")
    return build_shell_state(change, commit_title=title)
