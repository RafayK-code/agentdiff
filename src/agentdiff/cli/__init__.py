"""agentdiff CLI: discover stored changes and export their comments.

Read/consume surface of the human↔agent loop. Thin adapter over the ``Store``
protocol and the exporter; never ingests, creates, or links changes (that is
the TUI's job). Checkout-independent — no git, no "current change".

Exit-code / stderr contract (R9):

+----------------------------------------------------+------+------------------+
| Case                                               | Exit | Stream           |
+----------------------------------------------------+------+------------------+
| success (``changes``, ``export``, ``--version``)   | 0    | stdout (output)  |
| domain error (selector/change/branch/format)       | 1    | stderr: msg      |
| bad ``--root`` (exists, not a directory)           | 1    | stderr: msg      |
| store malformed record (``StoreError``)            | 1    | stderr: msg      |
| I/O error (unwritable ``--out``)                   | 1    | stderr: msg      |
| argparse parse failure                             | 2    | stderr (builtin) |
| bare ``agentdiff`` on a TTY                        | 0    | TUI launched     |
| bare ``agentdiff`` piped                           | 1    | stderr (usage)   |
+----------------------------------------------------+------+------------------+

A nonexistent ``--root`` is a lazy empty store, not an error (R9).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol, TextIO

from agentdiff import __version__
from agentdiff.cli import changes, export
from agentdiff.cli.common import store_for
from agentdiff.cli.errors import CliError
from agentdiff.store import Store, StoreError


class _Command(Protocol):
    def add_parser(
        self, subparsers: argparse._SubParsersAction[argparse.ArgumentParser]
    ) -> None: ...

    def run(self, args: argparse.Namespace, store: Store, out: TextIO) -> int: ...


_COMMANDS: dict[str, _Command] = {"changes": changes, "export": export}


def _run_bare(
    parser: argparse.ArgumentParser,
    out: TextIO,
    err: TextIO,
    *,
    root: Path,
    launch: Callable[[Path], int] | None,
) -> int:
    """Bare dispatch (R1a): launch the TUI on a TTY, usage when piped."""
    if not out.isatty():
        parser.print_usage(err)  # usage on stderr; piped context
        return 1
    if launch is None:
        from agentdiff.tui import run_tui

        launch = run_tui
    return launch(root)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentdiff",
        description="Read/consume CLI for agentdiff: discover changes and export "
        "comments for any agent harness.",
    )
    parser.add_argument(
        "--version", action="store_true", help="print the version and exit"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="repository root for the TUI (default: current directory)",
    )
    subparsers = parser.add_subparsers(
        dest="command",
        metavar="<command>",
        required=False,  # bare allowed (R1a)
    )
    changes.add_parser(subparsers)
    export.add_parser(subparsers)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    launch: Callable[[Path], int] | None = None,
) -> int:
    """Run the CLI. ``stdout``/``stderr`` default to ``sys.stdout``/``sys.stderr``
    (so capsys captures them); injected streams make the bare TTY branch
    deterministic. ``launch`` is the TUI entrypoint seam. Returns the process
    exit code (see module docstring)."""
    out = sys.stdout if stdout is None else stdout
    err = sys.stderr if stderr is None else stderr
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.version:  # R1b — before ANY dispatch
        out.write(f"agentdiff {__version__}\n")
        return 0
    if args.command is None:  # R1a — bare = TUI
        return _run_bare(parser, out, err, root=args.root or Path("."), launch=launch)
    try:
        store = store_for(args.root)  # factory only (R6)
        return _COMMANDS[args.command].run(args, store, out)
    except (CliError, StoreError, OSError) as exc:  # R1, R9
        err.write(f"agentdiff: {exc}\n")
        return 1
