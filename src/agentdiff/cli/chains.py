from __future__ import annotations

from datetime import datetime, timezone

from agentdiff.model import Change


def group_by_branch(changes: list[Change]) -> dict[str | None, list[Change]]:
    """Group changes by branch (None = patch imports)."""
    groups: dict[str | None, list[Change]] = {}
    for change in changes:
        groups.setdefault(change.branch, []).append(change)
    return groups


def _current_time(change: Change) -> datetime:
    current = change.current
    if current is not None and current.created_at is not None:
        return current.created_at
    if change.created_at is not None:
        return change.created_at
    return datetime.min.replace(tzinfo=timezone.utc)


def latest_change(changes: list[Change]) -> Change | None:
    """The change whose current version is newest, tie-broken by id (A8)."""
    if not changes:
        return None
    return max(changes, key=lambda change: (_current_time(change), change.id))
