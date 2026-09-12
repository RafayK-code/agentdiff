from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import Enum

from agentdiff.model.types import Change, Comment, FileDiff, Side, Version


class ShellStatus(str, Enum):
    READY = "READY"
    EMPTY = "EMPTY"
    ERROR = "ERROR"


class FileStatus(str, Enum):
    ADDED = "added"
    DELETED = "deleted"
    RENAMED = "renamed"
    MODIFIED = "modified"
    BINARY = "binary"


@dataclass(frozen=True)
class FileEntry:
    path: str
    old_path: str | None
    status: FileStatus
    additions: int
    deletions: int


@dataclass(frozen=True)
class FileContent:
    side: Side
    lines: tuple[str, ...]


@dataclass(frozen=True)
class ShellState:
    status: ShellStatus
    change: Change | None = None
    branch: str | None = None
    commit_title: str | None = None
    change_id: str | None = None
    base_revision: str | None = None
    head_revision: str | None = None
    files: tuple[FileEntry, ...] = ()
    contents: tuple[FileContent | None, ...] = ()
    selected: int = 0
    version_index: int = 0
    comments: tuple[Comment, ...] = ()
    message: str | None = None


def file_status(file: FileDiff) -> FileStatus:
    if file.is_binary:
        return FileStatus.BINARY
    if file.old_path is not None:
        return FileStatus.RENAMED
    if file.new_mode is not None and file.old_mode is None:
        return FileStatus.ADDED
    if file.old_mode is not None and file.new_mode is None:
        return FileStatus.DELETED
    return FileStatus.MODIFIED


def summarize_file(file: FileDiff) -> FileEntry:
    additions = sum(
        1 for hunk in file.hunks for line in hunk.lines if line.kind == "add"
    )
    deletions = sum(
        1 for hunk in file.hunks for line in hunk.lines if line.kind == "del"
    )
    return FileEntry(
        path=file.path,
        old_path=file.old_path,
        status=file_status(file),
        additions=additions,
        deletions=deletions,
    )


def _summarize_version(change: Change, version_index: int) -> tuple[FileEntry, ...]:
    if not change.versions:
        return ()
    index = max(0, min(version_index, len(change.versions) - 1))
    return tuple(summarize_file(file) for file in change.versions[index].files)


def build_shell_state(
    change: Change,
    *,
    contents: Sequence[FileContent | None] = (),
    comments: Sequence[Comment] = (),
    commit_title: str | None = None,
) -> ShellState:
    version_index = max(0, len(change.versions) - 1)
    return ShellState(
        status=ShellStatus.READY,
        change=change,
        branch=change.branch,
        commit_title=commit_title,
        change_id=change.id,
        base_revision=change.base_revision,
        head_revision=change.head_revision,
        files=_summarize_version(change, version_index),
        contents=tuple(contents),
        selected=0,
        version_index=version_index,
        comments=tuple(comments),
    )


def selected_version(state: ShellState) -> Version | None:
    change = state.change
    if change is None or not change.versions:
        return None
    index = max(0, min(state.version_index, len(change.versions) - 1))
    return change.versions[index]


def is_current_version(state: ShellState) -> bool:
    change = state.change
    if change is None or not change.versions:
        return False
    return state.version_index >= len(change.versions) - 1


def select_version(state: ShellState, delta: int) -> ShellState:
    change = state.change
    if change is None or not change.versions:
        return state
    index = max(0, min(state.version_index + delta, len(change.versions) - 1))
    if index == state.version_index:
        return state
    return replace(
        state,
        version_index=index,
        files=_summarize_version(change, index),
        selected=0,
    )


def empty_state(message: str = "Nothing to review.") -> ShellState:
    return ShellState(status=ShellStatus.EMPTY, message=message)


def error_state(message: str) -> ShellState:
    return ShellState(status=ShellStatus.ERROR, message=message)


def move_selection(index: int, count: int, delta: int) -> int:
    if count <= 0:
        return 0
    return max(0, min(count - 1, index + delta))


def select_file(state: ShellState, delta: int) -> ShellState:
    selected = move_selection(state.selected, len(state.files), delta)
    if selected == state.selected:
        return state
    return replace(state, selected=selected)


def format_header(state: ShellState) -> str:
    title = state.commit_title or ""
    header = f"agentdiff  {title}".rstrip()
    change = state.change
    if change is None or not change.versions:
        return header
    number = min(state.version_index, len(change.versions) - 1) + 1
    header = f"{header}  v{number} of {len(change.versions)}"
    if not is_current_version(state):
        header = f"{header} (history)"
    return header


def format_file(entry: FileEntry) -> str:
    if entry.status is FileStatus.RENAMED and entry.old_path is not None:
        path = f"{entry.old_path} \u2192 {entry.path}"
    else:
        path = entry.path
    return f"[{entry.status.value}] {path} (+{entry.additions} -{entry.deletions})"
