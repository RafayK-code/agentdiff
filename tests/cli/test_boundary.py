from __future__ import annotations

import inspect
import sys

FORBIDDEN = ("textual", "mcp", "agentdiff.mcp", "agentdiff.tui")


def test_cli_imports_no_ui_or_transport() -> None:
    for name in [
        n for n in sys.modules if n == "agentdiff.cli" or n.startswith("agentdiff.cli.")
    ]:
        del sys.modules[name]
    before = set(sys.modules)
    import agentdiff.cli  # noqa: F401

    added = set(sys.modules) - before
    assert not any(m == f or m.startswith(f + ".") for m in added for f in FORBIDDEN)
    main = agentdiff.cli.__dict__["main"]
    sig = inspect.signature(main)
    assert "argv" in sig.parameters
    for name, param in sig.parameters.items():
        if name in ("stdout", "stderr"):
            assert param.kind is inspect.Parameter.KEYWORD_ONLY
    main = agentdiff.cli.main
    sig = inspect.signature(main)
    assert "argv" in sig.parameters
    for name, param in sig.parameters.items():
        if name == "stdout" or name == "stderr":
            assert param.kind is inspect.Parameter.KEYWORD_ONLY
