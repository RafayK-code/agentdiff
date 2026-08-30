from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Final

from agentdiff.model import Change, Comment, CommentState, FileDiff

# R5. D6 policy (ARCHITECTURE.md §7): adding a field is a MINOR version bump;
# changing/removing a field, or renumbering `lines`, is a MAJOR version bump.
# `schema_version` is a `major.minor.patch` STRING so every bump kind is
# unambiguous and the encoding never needs to change: minor -> "1.1.0",
# major -> "2.0.0" (lower components reset to 0), patch (no shape change) ->
# "1.0.1". Initial contract is "1.0.0" (R5).
SCHEMA_VERSION: Final[str] = "1.0.0"


def _file_counts(file: FileDiff) -> tuple[int, int]:
    """(additions, deletions) summed over every hunk line kind. (R2)"""
    adds = sum(1 for h in file.hunks for ln in h.lines if ln.kind == "add")
    dels = sum(1 for h in file.hunks for ln in h.lines if ln.kind == "del")
    return adds, dels


def _iso8601(dt: datetime) -> str:
    """UTC ISO-8601, seconds precision, trailing 'Z' (matches §7 sketch)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (
        dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


def _file_block(file: FileDiff) -> dict[str, object]:
    """{path, additions, deletions, old_path} — field order pinned. (R2)"""
    additions, deletions = _file_counts(file)
    return {
        "path": file.path,
        "additions": additions,
        "deletions": deletions,
        "old_path": file.old_path,
    }


def _approval_block(change: Change) -> dict[str, object] | None:
    """{status, message, author, at} or None when not approved. (R2, D7)"""
    if change.approval is None:
        return None
    return {
        "status": change.approval.status,
        "message": change.approval.message,
        "author": change.approval.author,
        "at": _iso8601(change.approval.at),
    }


def _change_block(change: Change) -> dict[str, object]:
    """{id, base_revision, head_revision, approval, files} — order pinned. (R2)"""
    return {
        "id": change.id,
        "base_revision": change.base_revision,
        "head_revision": change.head_revision,
        "approval": _approval_block(change),
        "files": [_file_block(f) for f in change.files],
    }


def _comment_block(comment: Comment) -> dict[str, object]:
    """{id, file, side, lines, text, author, thread_id, state, drifted,
    created_at} — order pinned. (R3)"""
    if comment.range is None:
        side: str | None = None
        lines: list[int] | None = None
    else:
        side = comment.range.side.value  # "OLD" | "NEW"
        lines = [comment.range.start, comment.range.end]  # 1-based inclusive
    return {
        "id": comment.id,
        "file": comment.file,
        "side": side,
        "lines": lines,
        "text": comment.text,
        "author": comment.author,
        "thread_id": comment.thread_id,
        "state": comment.state.value,
        "drifted": comment.state is CommentState.DRIFTED,  # derived (R3)
        "created_at": _iso8601(comment.created_at),
    }


def export_json(change: Change, comments: list[Comment]) -> str:
    """Serialize a change + its comments to the §7 JSON contract (R1)."""
    doc = {
        "schema_version": SCHEMA_VERSION,
        "change": _change_block(change),
        "comments": [_comment_block(c) for c in comments],
    }
    return json.dumps(doc, indent=2, ensure_ascii=True) + "\n"
