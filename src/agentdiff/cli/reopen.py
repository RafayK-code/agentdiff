from __future__ import annotations

import argparse
from typing import TextIO

from agentdiff.anchor import reopen_reply
from agentdiff.cli.common import add_root_option
from agentdiff.cli.errors import CliError
from agentdiff.store import Store


def add_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    p = subparsers.add_parser(
        "reopen", help="reopen a comment as a reply on the current version"
    )
    add_root_option(p)
    p.add_argument("comment_id", metavar="ID", help="the comment id")
    p.add_argument("--message", default="Reopened.", help="the reply text")
    p.add_argument("--author", default="agentdiff", help="reply author")
    p.set_defaults(func=run)


def run(args: argparse.Namespace, store: Store, out: TextIO) -> int:
    comment = store.get_comment(args.comment_id)
    change = store.load_change(comment.change_id)
    if change is None:
        raise CliError(f"unknown change {comment.change_id!r}")
    reply = reopen_reply(comment, change, text=args.message, author=args.author)
    store.add_comment(reply)
    out.write(f"{reply.id}\n")
    return 0
