from __future__ import annotations

import argparse
from typing import TextIO

from agentdiff.anchor import ThreadState, group_threads
from agentdiff.cli.common import add_root_option
from agentdiff.cli.errors import CliError
from agentdiff.model import Comment, CommentState
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
        help="only this comment's own state (per-comment filter)",
    )
    p.add_argument(
        "--threads",
        action="store_true",
        help="group into reply threads (status marker + indented replies)",
    )
    p.add_argument(
        "--thread-state",
        dest="thread_state",
        choices=[state.value for state in ThreadState],
        help="only threads with this derived status; implies --threads",
    )
    p.add_argument(
        "--last-author",
        dest="last_author",
        choices=["human", "agent"],
        help="only threads whose last reply is from this role; implies --threads",
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


def _format_comment(comment: Comment, *, show_reply: bool = True) -> str:
    location = (
        "file-level"
        if comment.range is None
        else f"{comment.range.side.value} {comment.range.start}-{comment.range.end}"
    )
    reply = (
        f" in-reply-to={comment.in_reply_to}"
        if show_reply and comment.in_reply_to
        else ""
    )
    return (
        f"{comment.id}  {comment.revision}  {comment.file}  {location}  "
        f"[{comment.state.value}]{reply}  {comment.text}"
    )


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
    if not (
        args.threads or args.thread_state is not None or args.last_author is not None
    ):
        for comment in comments:
            out.write(_format_comment(comment) + "\n")
        return 0
    threads = group_threads(comments)
    if args.thread_state is not None:
        threads = tuple(t for t in threads if t.state.value == args.thread_state)
    if args.last_author is not None:
        threads = tuple(
            t for t in threads if t.last_author.value.lower() == args.last_author
        )
    if not threads:
        out.write("No threads.\n")
        return 0
    for thread in threads:
        root_line = _format_comment(thread.root, show_reply=False)
        out.write(
            f"[{thread.state.value}] last={thread.last_author.value.lower()} "
            f"{root_line}\n"
        )
        for reply in thread.replies:
            out.write(f"  {_format_comment(reply)}\n")
    return 0
