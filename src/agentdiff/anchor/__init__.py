from __future__ import annotations

import difflib
from collections.abc import Sequence
from datetime import datetime, timezone

from agentdiff.model.types import (
    Change,
    Comment,
    CommentState,
    FileDiff,
    LineRange,
    Side,
    Version,
    new_comment_id,
)

_FUZZY_THRESHOLD = 0.8

RESOLVE_AUTHOR = "agent"


def _normalize(text: str) -> str:
    return " ".join(text.split())


def _side_lines(file: FileDiff, side: Side) -> list[tuple[int, str]]:
    attr = "old_no" if side is Side.OLD else "new_no"
    result: list[tuple[int, str]] = []
    for hunk in file.hunks:
        for line in hunk.lines:
            number = getattr(line, attr)
            if number is not None:
                result.append((number, line.text))
    return result


def snapshot_lines(version: Version, file: str, line_range: LineRange) -> list[str]:
    """Raw context lines of ``line_range`` in ``version``'s ``file`` (R9)."""
    file_diff = next((f for f in version.files if f.path == file), None)
    if file_diff is None:
        return []
    return [
        text
        for number, text in _side_lines(file_diff, line_range.side)
        if line_range.start <= number <= line_range.end
    ]


def reanchor(comment: Comment, version: Version) -> LineRange | None:
    """Propose where ``comment`` lands in ``version``; None when not found (R9)."""
    if comment.range is None or not comment.anchor_snapshot:
        return None
    file = next((f for f in version.files if f.path == comment.file), None)
    if file is None:
        return None
    side = comment.range.side
    lines = _side_lines(file, side)
    snapshot = [_normalize(line) for line in comment.anchor_snapshot]
    span = len(snapshot)
    if span == 0 or span > len(lines):
        return None
    numbers = [number for number, _ in lines]
    normalized = [_normalize(text) for _, text in lines]
    for start in range(len(lines) - span + 1):
        if normalized[start : start + span] == snapshot:
            return LineRange(
                side=side, start=numbers[start], end=numbers[start + span - 1]
            )
    target = " ".join(snapshot)
    best_ratio = -1.0
    best_start: int | None = None
    for start in range(len(lines) - span + 1):
        candidate = " ".join(normalized[start : start + span])
        ratio = difflib.SequenceMatcher(None, target, candidate).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_start = start
    if best_start is not None and best_ratio >= _FUZZY_THRESHOLD:
        return LineRange(
            side=side,
            start=numbers[best_start],
            end=numbers[best_start + span - 1],
        )
    return None


def reopen_reply(
    comment: Comment,
    change: Change,
    *,
    text: str,
    author: str,
    now: datetime | None = None,
) -> Comment:
    """Build the ACTIVE reply that reopens ``comment`` on the current version.

    The original comment's state is not touched. (R6, R7)
    """
    current = change.current
    if current is None:
        raise ValueError(f"change {change.id!r} has no version to reopen onto")
    suggested = reanchor(comment, current)
    drifted = comment.range is not None and suggested is None
    timestamp = now if now is not None else datetime.now(timezone.utc)
    return Comment(
        id=new_comment_id(),
        change_id=change.id,
        revision=current.revision,
        file=comment.file,
        range=suggested,
        text=text,
        author=author,
        in_reply_to=comment.id,
        state=CommentState.ACTIVE,
        drifted=drifted,
        created_at=timestamp,
        updated_at=timestamp,
        anchor_snapshot=(
            snapshot_lines(current, comment.file, suggested)
            if suggested is not None
            else []
        ),
    )


def is_resolve_comment(comment: Comment) -> bool:
    """A resolve comment carries the RESOLVED state. (R7, Feedback 1)"""
    return comment.state is CommentState.RESOLVED


def _thread_root(comment: Comment, by_id: dict[str, Comment]) -> Comment:
    seen = {comment.id}
    current = comment
    while (
        current.in_reply_to is not None
        and current.in_reply_to in by_id
        and current.in_reply_to not in seen
    ):
        seen.add(current.in_reply_to)
        current = by_id[current.in_reply_to]
    return current


def thread_root(comment: Comment, comments: Sequence[Comment]) -> Comment:
    """The first comment of ``comment``'s reply chain. (Feedback 4)"""
    return _thread_root(comment, {item.id: item for item in comments})


def thread_root_id(comment: Comment, comments: Sequence[Comment]) -> str:
    """The id of the root of ``comment``'s reply chain. (R7, R8)"""
    return thread_root(comment, comments).id


def thread_members(
    comment: Comment, comments: Sequence[Comment]
) -> tuple[Comment, ...]:
    """Every member of ``comment``'s reply chain, ordered root→tip. (Feedback 4)"""
    by_id = {item.id: item for item in comments}
    root_id = _thread_root(comment, by_id).id
    members = [item for item in comments if _thread_root(item, by_id).id == root_id]
    if not any(item.id == comment.id for item in members):
        members.append(comment)
    return tuple(sorted(members, key=lambda item: (item.created_at, item.id)))


def thread_tip(comment: Comment, comments: Sequence[Comment]) -> Comment:
    """The last member of ``comment``'s chain by ``(created_at, id)``. (Feedback 4)"""
    return thread_members(comment, comments)[-1]


def is_resolved_thread(comment: Comment, comments: Sequence[Comment]) -> bool:
    """True when the last comment in the reply chain is a resolve comment. (R8)"""
    return is_resolve_comment(thread_tip(comment, comments))


def resolution_reply(
    comment: Comment,
    change: Change,
    *,
    author: str = RESOLVE_AUTHOR,
    now: datetime | None = None,
) -> Comment:
    """The RESOLVED reply that resolves ``comment``'s thread. (R7, Feedback 1)

    Resolving is a comment: this is an ordinary reply with ``state=RESOLVED``.
    The original comment is left untouched. Both the TUI and the CLI resolve
    through this one function so their behavior cannot drift.
    """
    current = change.current
    if current is None:
        raise ValueError(f"change {change.id!r} has no version to resolve onto")
    timestamp = now if now is not None else datetime.now(timezone.utc)
    return Comment(
        id=new_comment_id(),
        change_id=change.id,
        revision=current.revision,
        file=comment.file,
        range=comment.range,
        text="resolved",
        author=author,
        in_reply_to=comment.id,
        state=CommentState.RESOLVED,
        drifted=False,
        created_at=timestamp,
        updated_at=timestamp,
        anchor_snapshot=(
            snapshot_lines(current, comment.file, comment.range)
            if comment.range is not None
            else []
        ),
    )


__all__ = [
    "RESOLVE_AUTHOR",
    "is_resolve_comment",
    "is_resolved_thread",
    "reanchor",
    "reopen_reply",
    "resolution_reply",
    "snapshot_lines",
    "thread_members",
    "thread_root",
    "thread_root_id",
    "thread_tip",
]
