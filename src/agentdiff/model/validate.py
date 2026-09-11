from __future__ import annotations

from agentdiff.model.types import Change, Comment, FileDiff, Side


class CommentValidationError(ValueError):
    """A comment does not fit its owning Change (R6)."""


def _max_line(file: FileDiff, side: Side) -> int:
    """Highest line number the file reaches on `side`, else 0 (no valid ranges)."""
    attr = "old_no" if side is Side.OLD else "new_no"
    return max(
        (
            getattr(line, attr)
            for h in file.hunks
            for line in h.lines
            if getattr(line, attr) is not None
        ),
        default=0,
    )


def validate_comment(comment: Comment, change: Change) -> None:
    """Raise CommentValidationError if the comment does not fit the change. (R8)"""
    version = change.version_for(comment.revision)
    if version is None:
        raise CommentValidationError(
            f"revision {comment.revision!r} is not a version of change {change.id!r}"
        )
    file = next((f for f in version.files if f.path == comment.file), None)
    if file is None:
        raise CommentValidationError(
            f"file {comment.file!r} is not in revision {comment.revision!r} "
            f"of change {change.id!r}"
        )
    if comment.range is None:
        return
    top = _max_line(file, comment.range.side)
    if top == 0 or comment.range.end > top:
        raise CommentValidationError(
            f"range {comment.range} exceeds {comment.range.side}-side line "
            f"numbering of {comment.file!r} (max line {top})"
        )
