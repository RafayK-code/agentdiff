from __future__ import annotations

import argparse
from typing import TextIO

from agentdiff.anchor import is_resolved_thread, resolution_reply
from agentdiff.cli.common import add_root_option
from agentdiff.cli.errors import CliError
from agentdiff.store import Store


def add_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    p = subparsers.add_parser(
        "resolve", help="resolve a comment by replying with a RESOLVED comment"
    )
    add_root_option(p)
    p.add_argument("comment_id", metavar="ID", help="the comment id")
    p.set_defaults(func=run)


def run(args: argparse.Namespace, store: Store, out: TextIO) -> int:
    comment = store.get_comment(args.comment_id)
    change = store.load_change(comment.change_id)
    if change is None:
        raise CliError(f"unknown change {comment.change_id!r}")
    comments = store.list_comments(change.id, include_closed=True)
    if not is_resolved_thread(comment, comments):
        reply = resolution_reply(comment, change)
        store.add_comment(reply)
        out.write(f"{reply.id}\n")
    return 0
