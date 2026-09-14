from __future__ import annotations

import argparse
from typing import TextIO

from agentdiff.cli.common import add_root_option
from agentdiff.cli.errors import CliError
from agentdiff.diff.serialize import serialize_file
from agentdiff.model import FileDiff, Hunk, LineRange, Side
from agentdiff.store import Store


def add_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    p = subparsers.add_parser(
        "show", help="show a comment with the diff hunks it anchors to"
    )
    add_root_option(p)
    p.add_argument("comment_id", metavar="COMMENT-ID", help="the comment id")
    p.set_defaults(func=run)


def _hunk_span(hunk: Hunk, side: Side) -> tuple[int, int]:
    if side is Side.OLD:
        return hunk.old_start, hunk.old_start + hunk.old_count - 1
    return hunk.new_start, hunk.new_start + hunk.new_count - 1


def hunks_for(file: FileDiff, line_range: LineRange | None) -> tuple[Hunk, ...]:
    """Hunks overlapping ``line_range`` on its side; all hunks when file-level
    or when nothing overlaps. Pure. (R6)"""
    if line_range is None:
        return tuple(file.hunks)
    overlapping = tuple(
        hunk
        for hunk in file.hunks
        if _hunk_span(hunk, line_range.side)[0] <= line_range.end
        and line_range.start <= _hunk_span(hunk, line_range.side)[1]
    )
    return overlapping or tuple(file.hunks)


def _location(line_range: LineRange | None) -> str:
    if line_range is None:
        return "file-level"
    return f"{line_range.side.value} {line_range.start}-{line_range.end}"


def run(args: argparse.Namespace, store: Store, out: TextIO) -> int:
    comment = store.get_comment(args.comment_id)
    change = store.load_change(comment.change_id)
    if change is None:
        raise CliError(f"unknown change {comment.change_id!r}")
    version = change.version_for(comment.revision)
    if version is None:
        raise CliError(f"unknown revision {comment.revision!r}")
    file = next((f for f in version.files if f.path == comment.file), None)
    if file is None:
        raise CliError(f"unknown file {comment.file!r}")
    out.write(
        f"{comment.id}  {comment.revision}  {comment.file}  "
        f"{_location(comment.range)}  [{comment.state.value}]  "
        f"{comment.author}: {comment.text}\n"
    )
    out.write(serialize_file(file, hunks_for(file, comment.range)))
    return 0
