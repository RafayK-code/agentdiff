from __future__ import annotations

import argparse
from pathlib import Path
from typing import TextIO

from agentdiff.cli.chains import latest_change
from agentdiff.cli.common import add_root_option
from agentdiff.cli.errors import CliError
from agentdiff.export import export_json, export_markdown
from agentdiff.store import Store

_FORMATS = ("json", "markdown")


def add_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    p = subparsers.add_parser(
        "export", help="export a change's comments (§7 JSON or markdown)"
    )
    add_root_option(p)
    p.add_argument("--change", metavar="ID", help="specific change to export")
    p.add_argument(
        "--branch", metavar="NAME", help="export this branch's latest change"
    )
    p.add_argument(
        "--format",
        default="markdown",
        help="'json' (machine contract) or 'markdown' (default)",
    )
    p.add_argument(
        "--out", type=Path, metavar="FILE", help="write to FILE instead of stdout"
    )
    p.add_argument(
        "--include-closed",
        action="store_true",
        help="include CLOSED comments (hidden by default)",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace, store: Store, out: TextIO) -> int:
    selectors = sum(1 for s in (args.change, args.branch) if s is not None)
    if selectors != 1:
        raise CliError(
            "export requires exactly one of --change <id> or --branch <name>"
        )
    if args.format not in _FORMATS:
        raise CliError(
            f"unknown export format {args.format!r} (expected 'json' or 'markdown')"
        )
    if args.change is not None:
        change = store.load_change(args.change)
        if change is None:
            raise CliError(f"unknown change {args.change!r}")
    else:
        branch_changes = store.list_changes(branch=args.branch)
        if not branch_changes:
            raise CliError(f"unknown branch {args.branch!r}")
        change = latest_change(branch_changes)
        if change is None:
            raise CliError(f"branch {args.branch!r} has no changes")
    comments = store.list_comments(change.id, include_closed=True)
    text = (
        export_json(change, comments, include_closed=args.include_closed)
        if args.format == "json"
        else export_markdown(change, comments, include_closed=args.include_closed)
    )
    if args.out is not None:
        args.out.write_text(text, encoding="utf-8")
    else:
        out.write(text)
    return 0
