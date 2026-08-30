from __future__ import annotations

import ast
from pathlib import Path

EXPORT_DIR = Path(__file__).parents[2] / "src" / "agentdiff" / "export"

FORBIDDEN = (
    "agentdiff.store",
    "agentdiff.cli",
    "agentdiff.mcp",
    "agentdiff.tui",
    "agentdiff.diff",
    "textual",
)


def _imported_modules(source: str) -> list[str]:
    tree = ast.parse(source)
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            modules.append(node.module or "")
    return modules


def test_export_imports_only_model() -> None:
    for py in sorted(EXPORT_DIR.rglob("*.py")):
        for module in _imported_modules(py.read_text(encoding="utf-8")):
            assert not any(
                module == f or module.startswith(f + ".") for f in FORBIDDEN
            ), f"{py.name} imports {module}"
