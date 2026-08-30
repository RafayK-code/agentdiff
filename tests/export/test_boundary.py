from __future__ import annotations

import sys

FORBIDDEN = (
    "agentdiff.store",
    "agentdiff.cli",
    "agentdiff.mcp",
    "agentdiff.tui",
    "agentdiff.diff",
    "textual",
)


def test_export_imports_no_forbidden_packages() -> None:
    for name in [
        n
        for n in sys.modules
        if n == "agentdiff.export" or n.startswith("agentdiff.export.")
    ]:
        del sys.modules[name]
    before = set(sys.modules)
    import agentdiff.export  # noqa: F401

    added = set(sys.modules) - before
    assert not any(m == f or m.startswith(f + ".") for m in added for f in FORBIDDEN)
