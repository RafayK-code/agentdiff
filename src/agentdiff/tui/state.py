from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from agentdiff.model.types import Change, FileDiff


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
class ShellState:
    status: ShellStatus
    change: Change | None = None
    branch: str | None = None
    commit_title: str | None = None
    change_id: str | None = None
    base_revision: str | None = None
    head_revision: str | None = None
    files: tuple[FileEntry, ...] = ()
    previews: tuple[str, ...] = ()
    selected: int = 0
    message: str | None = None

    @property
    def current_preview(self) -> str:
        if self.previews and 0 <= self.selected < len(self.previews):
            return self.previews[self.selected]
        return self.message or ""


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


def render_diff_placeholder(file: FileDiff) -> str:
    entry = summarize_file(file)
    lines = [
        f"{entry.path} ({entry.status.value}, +{entry.additions} -{entry.deletions})"
    ]
    if file.is_binary:
        lines.append("(binary file)")
    elif not file.hunks:
        lines.append("(no hunks)")
    else:
        for hunk in file.hunks:
            lines.append(
                f"@@ -{hunk.old_start},{hunk.old_count} "
                f"+{hunk.new_start},{hunk.new_count} @@"
            )
    return "\n".join(lines)


def build_shell_state(change: Change, commit_title: str | None = None) -> ShellState:
    return ShellState(
        status=ShellStatus.READY,
        change=change,
        branch=change.branch,
        commit_title=commit_title,
        change_id=change.id,
        base_revision=change.base_revision,
        head_revision=change.head_revision,
        files=tuple(summarize_file(file) for file in change.files),
        previews=tuple(render_diff_placeholder(file) for file in change.files),
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
    selected = move_selection(state.selected, len(state.previews), delta)
    if selected == state.selected:
        return state
    return ShellState(
        status=state.status,
        change=state.change,
        branch=state.branch,
        commit_title=state.commit_title,
        change_id=state.change_id,
        base_revision=state.base_revision,
        head_revision=state.head_revision,
        files=state.files,
        previews=state.previews,
        selected=selected,
        message=state.message,
    )


def format_header(state: ShellState) -> str:
    title = state.commit_title or ""
    return f"agentdiff  {title}".rstrip()


def format_file(entry: FileEntry) -> str:
    if entry.status is FileStatus.RENAMED and entry.old_path is not None:
        path = f"{entry.old_path} \u2192 {entry.path}"
    else:
        path = entry.path
    return f"[{entry.status.value}] {path} (+{entry.additions} -{entry.deletions})"
