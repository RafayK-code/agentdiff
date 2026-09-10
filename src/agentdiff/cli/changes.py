from __future__ import annotations

import argparse
from typing import TextIO

from agentdiff.cli.chains import branch_tip, group_by_branch, order_chain
from agentdiff.cli.common import add_root_option
from agentdiff.model import Change
from agentdiff.store import Store


def add_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    p = subparsers.add_parser(
        "changes", help="list stored changes across branches (or one branch's chain)"
    )
    add_root_option(p)
    p.add_argument(
        "--branch",
        metavar="NAME",
        help="only show this branch's chain (default: all branches)",
    )
    p.set_defaults(func=run)


def _branch_label(branch: str | None) -> str:
    return "(no branch)" if branch is None else branch


def _branch_sort_key(branch: str | None) -> tuple[int, str]:
    return (0, "") if branch is None else (1, branch)


def _revision(rev: str | None) -> str:
    return "(none)" if rev is None else rev


def _change_line(
    position: int, change: Change, comment_count: int, is_tip: bool
) -> str:
    count = f"{comment_count} comment" + ("" if comment_count == 1 else "s")
    base = _revision(change.base_revision)
    head = _revision(change.head_revision)
    tip = "  (tip)" if is_tip else ""
    return f"  v{position} {change.id}  {base}→{head}  {count}{tip}"


def run(args: argparse.Namespace, store: Store, out: TextIO) -> int:
    changes_list = store.list_changes(branch=args.branch)
    if not changes_list:
        out.write("No changes.\n")
        return 0
    groups = group_by_branch(changes_list)
    for branch in sorted(groups, key=_branch_sort_key):
        out.write(f"{_branch_label(branch)}\n")
        ordered = order_chain(groups[branch])
        tip = branch_tip(groups[branch])
        tip_id = tip.id if tip is not None else None
        for position, change in enumerate(ordered, start=1):
            count = len(store.list_comments(change.id))
            out.write(_change_line(position, change, count, change.id == tip_id))
            out.write("\n")
    return 0
