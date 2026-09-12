from __future__ import annotations

import argparse
from typing import TextIO

from agentdiff.anchor import thread_members
from agentdiff.cli.common import add_root_option
from agentdiff.cli.errors import CliError
from agentdiff.store import Store


def add_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    p = subparsers.add_parser("close", help="close a thread (by its root comment id)")
    add_root_option(p)
    p.add_argument(
        "thread_id",
        metavar="ID",
        help="the thread's root comment id (threads[].root from the export)",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace, store: Store, out: TextIO) -> int:
    """Close the whole thread. (Feedback 4)"""
    root = store.get_comment(args.thread_id)
    if root.in_reply_to is not None:
        raise CliError(
            f"{args.thread_id!r} is not a thread root; pass the thread's root id"
        )
    comments = store.list_comments(root.change_id, include_closed=True)
    for member in thread_members(root, comments):
        store.close_comment(member.id)
    return 0
