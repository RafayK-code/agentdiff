from __future__ import annotations

import argparse
from typing import TextIO

from agentdiff.anchor import thread_members
from agentdiff.cli.common import add_root_option
from agentdiff.store import Store


def add_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    p = subparsers.add_parser("close", help="close a comment (human verdict)")
    add_root_option(p)
    p.add_argument("comment_id", metavar="ID", help="the comment id")
    p.set_defaults(func=run)


def run(args: argparse.Namespace, store: Store, out: TextIO) -> int:
    """Close the whole thread containing the comment. (Feedback 4)"""
    comment = store.get_comment(args.comment_id)
    comments = store.list_comments(comment.change_id, include_closed=True)
    for member in thread_members(comment, comments):
        store.close_comment(member.id)
    return 0
