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
    read_file_at_revision,
)
from agentdiff.model.types import Change, Comment, FileDiff, Side
from agentdiff.store import Store, StoreError, create_store
from agentdiff.tui.state import (
    FileContent,
    ShellState,
    build_shell_state,
    empty_state,
    error_state,
)


def _load_content(
    file: FileDiff,
    change: Change,
    *,
    runner: CommandRunner | None,
    cwd: Path,
) -> FileContent | None:
    if file.is_binary or not file.hunks:
        return None
    if file.old_mode is not None and file.new_mode is None:
        revision = change.base_revision
        side = Side.OLD
    else:
        revision = change.head_revision
        side = Side.NEW
    if revision is None:
        return None
    try:
        text = read_file_at_revision(revision, file.path, runner=runner, cwd=cwd)
    except OSError:
        return None
    if text is None:
        return None
    return FileContent(side=side, lines=tuple(text.splitlines()))


def load_comments(store: Store, change_id: str) -> tuple[Comment, ...]:
    """Load a change's comments, including CLOSED, in stored order. (R2, R10)"""
    return tuple(store.list_comments(change_id, include_closed=True))


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
    active_store = store if store is not None else create_store(root)
    try:
        active_store.save_change(change)
        comments = load_comments(active_store, change.id)
    except StoreError as exc:
        return error_state(f"store error: {exc}")
    contents = tuple(
        _load_content(file, change, runner=runner, cwd=root) for file in change.files
    )
    return build_shell_state(
        change, contents=contents, comments=comments, commit_title=title
    )
