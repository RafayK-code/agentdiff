from __future__ import annotations

from agentdiff.model import Change


def group_by_branch(changes: list[Change]) -> dict[str | None, list[Change]]:
    """Group changes by branch (None = patch imports)."""
    groups: dict[str | None, list[Change]] = {}
    for change in changes:
        groups.setdefault(change.branch, []).append(change)
    return groups


def order_chain(changes: list[Change]) -> list[Change]:
    """One branch's changes in head→tip order, following prev_change links.

    Heads are changes whose ``prev_change`` is None or points outside the set;
    each head's chain is walked deterministically (seen-set guards cycles).
    """
    by_id = {c.id: c for c in changes}
    children: dict[str, list[str]] = {}
    for change in changes:
        if change.prev_change in by_id:
            children.setdefault(change.prev_change, []).append(change.id)
    for links in children.values():
        links.sort()
    ordered: list[Change] = []
    seen: set[str] = set()
    heads = sorted(
        (c for c in changes if c.prev_change not in by_id), key=lambda c: c.id
    )
    for head in heads:
        current = head
        while current is not None and current.id not in seen:
            seen.add(current.id)
            ordered.append(current)
            followers = children.get(current.id, [])
            current = by_id[followers[0]] if followers else None
    return ordered


def branch_tip(changes: list[Change]) -> Change | None:
    """The change no same-branch change references (its id appears as no
    ``prev_change``); None for an empty or cyclic set."""
    if not changes:
        return None
    referenced = {c.prev_change for c in changes if c.prev_change is not None}
    tips = [c for c in changes if c.id not in referenced]
    if len(tips) == 1:
        return tips[0]
    return None
