from __future__ import annotations

import argparse
from pathlib import Path

from agentdiff.cli.errors import CliError
from agentdiff.store import Store, create_store


def add_root_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("."),
        metavar="PATH",
        help="repo root containing .agentdiff/ (default: current directory)",
    )


def store_for(root: Path) -> Store:
    """Factory through the Store protocol, with a bad-`--root` guard (R7)."""
    if root.exists() and not root.is_dir():
        raise CliError(f"--root {str(root)} is not a directory")
    return create_store(root)
