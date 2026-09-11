from __future__ import annotations

import argparse
from typing import TextIO

from agentdiff.cli.common import add_root_option
from agentdiff.cli.errors import CliError
from agentdiff.model import CommentState
from agentdiff.store import Store


def add_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    p = subparsers.add_parser("list", help="list a change's comments")
    add_root_option(p)
    p.add_argument("--change", metavar="ID", required=True, help="the change id")
    p.add_argument("--revision", metavar="REV", help="only this version's comments")
    p.add_argument("--file", metavar="PATH", help="only this file's comments")
    p.add_argument(
        "--state",
        choices=[state.value.lower() for state in CommentState],
        help="only this state's comments",
    )
    p.add_argument(
        "--include-closed",
        action="store_true",
        help="include CLOSED comments (hidden by default)",
    )
    p.set_defaults(func=run)


def _state(value: str | None) -> CommentState | None:
    if value is None:
        return None
    try:
        return CommentState(value.upper())
    except ValueError as exc:
        raise CliError(f"unknown comment state {value!r}") from exc


def run(args: argparse.Namespace, store: Store, out: TextIO) -> int:
    comments = store.list_comments(
        args.change,
        revision=args.revision,
        file=args.file,
        state=_state(args.state),
        include_closed=args.include_closed,
    )
    if not comments:
        out.write("No comments.\n")
        return 0
    for comment in comments:
        location = (
            "file-level"
            if comment.range is None
            else f"{comment.range.side.value} {comment.range.start}-{comment.range.end}"
        )
        reply = f" in-reply-to={comment.in_reply_to}" if comment.in_reply_to else ""
        out.write(
            f"{comment.id}  {comment.revision}  {comment.file}  {location}  "
            f"[{comment.state.value}]{reply}  {comment.text}\n"
        )
    return 0
