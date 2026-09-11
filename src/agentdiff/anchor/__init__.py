from __future__ import annotations

import difflib
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


__all__ = ["reanchor", "reopen_reply", "snapshot_lines"]
