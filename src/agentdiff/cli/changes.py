from __future__ import annotations

import argparse
from typing import TextIO

from agentdiff.cli.chains import group_by_branch
from agentdiff.cli.common import add_root_option
from agentdiff.cli.errors import CliError
from agentdiff.model import Change
from agentdiff.store import Store


def add_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    p = subparsers.add_parser(
        "changes", help="list stored changes across branches (with their versions)"
    )
    add_root_option(p)
    p.add_argument(
        "--branch",
        metavar="NAME",
        help="only show this branch's changes (default: all branches)",
    )
    p.add_argument(
        "--revision",
        "--commit",
        dest="revision",
        metavar="SHA",
        help="find the change whose versions include this revision (commit SHA) "
        "and print its id (accepts an abbreviated SHA)",
    )
    p.add_argument(
        "--include-closed",
        action="store_true",
        help="count CLOSED comments too (hidden by default)",
    )
    p.set_defaults(func=run)


def _branch_label(branch: str | None) -> str:
    return "(no branch)" if branch is None else branch


def _branch_sort_key(branch: str | None) -> tuple[int, str]:
    return (0, "") if branch is None else (1, branch)


def _revision(rev: str | None) -> str:
    return "(none)" if rev is None else rev


def _change_line(change: Change, comment_count: int) -> str:
    revisions = ",".join(version.revision for version in change.versions) or "(none)"
    count = f"{comment_count} comment" + ("" if comment_count == 1 else "s")
    base = _revision(change.base_revision)
    return (
        f"  {change.id}  {base}  versions={len(change.versions)}  "
        f"[{revisions}]  {count}"
    )


def _find_by_revision(changes_list: list[Change], revision: str) -> Change:
    """The change whose versions include ``revision`` (exact or abbreviated)."""
    matches = [
        change
        for change in changes_list
        if any(
            version.revision == revision or version.revision.startswith(revision)
            for version in change.versions
        )
    ]
    if not matches:
        raise CliError(f"no change contains revision {revision!r}")
    if len(matches) > 1:
        ids = ", ".join(change.id for change in matches)
        raise CliError(f"revision {revision!r} is ambiguous: matches {ids}")
    return matches[0]


def run(args: argparse.Namespace, store: Store, out: TextIO) -> int:
    changes_list = store.list_changes(branch=args.branch)
    if args.revision is not None:
        out.write(f"{_find_by_revision(changes_list, args.revision).id}\n")
        return 0
    if not changes_list:
        out.write("No changes.\n")
        return 0
    groups = group_by_branch(changes_list)
    for branch in sorted(groups, key=_branch_sort_key):
        out.write(f"{_branch_label(branch)}\n")
        for change in sorted(groups[branch], key=lambda c: c.id):
            count = len(
                store.list_comments(change.id, include_closed=args.include_closed)
            )
            out.write(_change_line(change, count))
            out.write("\n")
    return 0
