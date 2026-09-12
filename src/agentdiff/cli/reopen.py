from __future__ import annotations

import argparse
from typing import TextIO

from agentdiff.anchor import reanchor_thread, reopen_reply, thread_tip
from agentdiff.cli.common import add_root_option
from agentdiff.cli.errors import CliError
from agentdiff.store import Store


def add_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    p = subparsers.add_parser(
        "reopen",
        help="reopen a thread (by its root comment id) as a reply on the "
        "current version",
    )
    add_root_option(p)
    p.add_argument(
        "thread_id",
        metavar="ID",
        help="the thread's root comment id (threads[].root from the export)",
    )
    p.add_argument("--message", default="Reopened.", help="the reply text")
    p.add_argument("--author", default="agentdiff", help="reply author")
    p.set_defaults(func=run)


def run(args: argparse.Namespace, store: Store, out: TextIO) -> int:
    root = store.get_comment(args.thread_id)
    if root.in_reply_to is not None:
        raise CliError(
            f"{args.thread_id!r} is not a thread root; pass the thread's root id"
        )
    change = store.load_change(root.change_id)
    if change is None:
        raise CliError(f"unknown change {root.change_id!r}")
    comments = store.list_comments(change.id, include_closed=True)
    reply = reopen_reply(root, change, text=args.message, author=args.author)
    reply = reply.model_copy(update={"in_reply_to": thread_tip(root, comments).id})
    for member in reanchor_thread(root, change, comments, anchor=reply.range):
        store.update_comment(member)
    store.add_comment(reply)
    out.write(f"{reply.id}\n")
    return 0
