from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Final

from agentdiff.anchor import Thread, group_threads
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
    """{id, branch, base_revision, current_revision, versions, approval, files}
    — order pinned per §7; branch/base nullable (R12)."""
    return {
        "id": change.id,
        "branch": change.branch,
        "base_revision": change.base_revision,
        "current_revision": change.head_revision,
        "versions": [version.revision for version in change.versions],
        "approval": _approval_block(change),
        "files": [_file_block(f) for f in change.files],
    }


def _comment_block(comment: Comment) -> dict[str, object]:
    """{id, revision, file, side, lines, context, text, author, in_reply_to,
    state, drifted, created_at} — order pinned per §7. (R5/R12)

    ``side`` is the explicit OLD/NEW marker (``null`` for file-level) and
    ``context`` is the stored ``anchor_snapshot`` projected verbatim — the
    removed lines for ``OLD``, the added/current lines for ``NEW``.
    """
    if comment.range is None:
        side: str | None = None
        lines: list[int] | None = None
    else:
        side = comment.range.side.value  # "OLD" | "NEW"
        lines = [comment.range.start, comment.range.end]  # 1-based inclusive
    return {
        "id": comment.id,
        "revision": comment.revision,
        "file": comment.file,
        "side": side,
        "lines": lines,
        "context": list(comment.anchor_snapshot),
        "text": comment.text,
        "author": comment.author,
        "in_reply_to": comment.in_reply_to,
        "state": comment.state.value,
        "drifted": comment.drifted,
        "created_at": _iso8601(comment.created_at),
    }


def _thread_block(thread: Thread) -> dict[str, object]:
    """{root, state, comments} — one entry per reply thread. (R6)"""
    return {
        "root": thread.root.id,
        "state": thread.state.value,
        "comments": [member.id for member in thread.members],
    }


def export_json(
    change: Change, comments: list[Comment], *, include_closed: bool = False
) -> str:
    """Serialize a change + its comments to the §7 JSON contract (R1).

    ``CLOSED`` comments are omitted unless ``include_closed=True`` (R7)."""
    visible = [
        c for c in comments if include_closed or c.state is not CommentState.CLOSED
    ]
    doc = {
        "schema_version": SCHEMA_VERSION,
        "change": _change_block(change),
        "comments": [_comment_block(c) for c in visible],
        "threads": [_thread_block(t) for t in group_threads(visible)],
    }
    return json.dumps(doc, indent=2, ensure_ascii=True) + "\n"
