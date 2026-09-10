from __future__ import annotations

import sys


def test_tui_imports_no_mcp() -> None:
    for name in [
        n for n in sys.modules if n == "agentdiff.tui" or n.startswith("agentdiff.tui.")
    ]:
        del sys.modules[name]
    before = set(sys.modules)
    import agentdiff.tui  # noqa: F401

    added = set(sys.modules) - before
    assert not any(
        m == "agentdiff.mcp" or m.startswith("agentdiff.mcp.") for m in added
    )


def test_core_packages_import_no_textual() -> None:
    for package in (
        "agentdiff.model",
        "agentdiff.diff",
        "agentdiff.store",
        "agentdiff.anchor",
    ):
        for name in [
            n for n in sys.modules if n == package or n.startswith(package + ".")
        ]:
            del sys.modules[name]
        before = set(sys.modules)
        __import__(package)
        added = set(sys.modules) - before
        assert not any(m == "textual" or m.startswith("textual.") for m in added), (
            package
        )
