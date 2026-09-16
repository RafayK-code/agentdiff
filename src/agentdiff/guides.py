"""Read the usage guides that ship with the package (R3).

UI-free so the packaging check can read a guide without importing Textual, and
so the resource path lives in one place.
"""

from __future__ import annotations

from importlib.resources import files

GUIDE_DIR = "docs"
AGENT_GUIDE = "agent-guide.md"
TUI_GUIDE = "tui-guide.md"


def read_guide(name: str) -> str:
    """Return the text of a packaged usage guide (R3).

    ``name`` is a file in ``agentdiff/docs/`` (e.g. ``TUI_GUIDE``). Reads via
    ``importlib.resources`` so it resolves from an installed wheel with no repo
    checkout. Raises ``FileNotFoundError`` when the resource is absent.
    """
    return (files("agentdiff") / GUIDE_DIR / name).read_text(encoding="utf-8")
