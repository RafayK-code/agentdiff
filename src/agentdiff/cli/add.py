from __future__ import annotations

import argparse
import re
from datetime import datetime, timezone
from typing import TextIO

from agentdiff.anchor import snapshot_lines
from agentdiff.cli.common import add_role_option, add_root_option, parse_role
from agentdiff.cli.errors import CliError
from agentdiff.model import (
    Change,
    Comment,
    CommentState,
    LineRange,
    Side,
    new_comment_id,
)
from agentdiff.store import Store

_LINES_RE = re.compile(r"^(\d+)(?:-(\d+))?$")


def add_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    p = subparsers.add_parser(
        "add", help="author a root comment or reply on the current version"
    )
    add_root_option(p)
    p.add_argument("file", metavar="PATH", help="new-side path")
    p.add_argument("--change", metavar="ID", help="the change to comment on")
    p.add_argument("--lines", metavar="START-END", help="line range, e.g. 300-364")
    p.add_argument(
        "--side",
        default="new",
        choices=["new", "old"],
        help="which side the lines refer to (default: new)",
    )
    p.add_argument("--message", required=True, help="the comment text")
    p.add_argument("--author", default="agentdiff", help="comment author")
    add_role_option(p)
    p.add_argument(
        "--in-reply-to",
        dest="in_reply_to",
        metavar="ID",
        help="parent comment id (makes this a reply)",
    )
    p.set_defaults(func=run)


def _line_range(lines: str | None, side: str) -> LineRange | None:
    if lines is None:
        return None
    match = _LINES_RE.match(lines)
    if match is None:
        raise CliError(f"invalid --lines {lines!r} (expected START-END)")
    start = int(match.group(1))
    end = int(match.group(2) or start)
    try:
        return LineRange(
            side=Side.NEW if side == "new" else Side.OLD, start=start, end=end
        )
    except ValueError as exc:
        raise CliError(f"invalid --lines {lines!r}: {exc}") from exc


def _resolve_change(
    args: argparse.Namespace, store: Store
) -> tuple[Change, Comment | None]:
    if args.change is not None:
        change = store.load_change(args.change)
        if change is None:
            raise CliError(f"unknown change {args.change!r}")
        return change, None
    if args.in_reply_to is not None:
        parent = store.get_comment(args.in_reply_to)
        change = store.load_change(parent.change_id)
        if change is None:
            raise CliError(f"unknown change {parent.change_id!r}")
        return change, parent
    raise CliError("add requires --change or --in-reply-to")


def run(args: argparse.Namespace, store: Store, out: TextIO) -> int:
    change, parent = _resolve_change(args, store)
    current = change.current
    if current is None:
        raise CliError(f"change {change.id!r} has no version to comment on")
    if args.lines is not None:
        line_range = _line_range(args.lines, args.side)
        file = args.file
    elif parent is not None:
        line_range = parent.range
        file = parent.file
    else:
        line_range = None
        file = args.file
    now = datetime.now(timezone.utc)
    comment = Comment(
        id=new_comment_id(),
        change_id=change.id,
        revision=current.revision,
        file=file,
        range=line_range,
        text=args.message,
        author=args.author,
        role=parse_role(args.role),
        in_reply_to=args.in_reply_to,
        state=CommentState.ACTIVE,
        created_at=now,
        updated_at=now,
        anchor_snapshot=(
            snapshot_lines(current, file, line_range) if line_range else []
        ),
    )
    store.add_comment(comment)
    out.write(f"{comment.id}\n")
    return 0
