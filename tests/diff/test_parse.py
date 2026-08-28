from __future__ import annotations

import ast
import hashlib
import inspect
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest
from tests.diff.conftest import load_fixture, load_malformed

from agentdiff.diff.parse import DiffParseError, parse_unified_diff
from agentdiff.model.types import FileDiff, Hunk, Line

BASIC = load_fixture("basic.patch")

_BASIC_EXPECTED = [
    FileDiff(
        path="src/foo.py",
        old_path=None,
        old_mode=None,
        new_mode=None,
        is_binary=False,
        hunks=[
            Hunk(
                old_start=1,
                old_count=3,
                new_start=1,
                new_count=3,
                lines=[
                    Line(kind="ctx", old_no=1, new_no=1, text="ctx1"),
                    Line(kind="del", old_no=2, new_no=None, text="removed"),
                    Line(kind="add", old_no=None, new_no=2, text="added"),
                    Line(kind="ctx", old_no=3, new_no=3, text="ctx2"),
                ],
            )
        ],
    )
]


def test_r1_parse_basic() -> None:
    change = parse_unified_diff(BASIC)
    assert change.files == _BASIC_EXPECTED


def test_r1_id_deterministic_stable() -> None:
    a = parse_unified_diff(BASIC)
    b = parse_unified_diff(BASIC)
    expected = "chg-" + hashlib.sha256(BASIC.encode("utf-8")).hexdigest()[:16]
    assert a.id == b.id
    assert a.id == expected
    assert a.id


def test_r1_id_changes_with_content() -> None:
    a = parse_unified_diff(BASIC)
    b = parse_unified_diff(BASIC.replace("ctx1", "ctx0"))
    assert a.id != b.id


def test_r1_no_io_no_git(tmp_path: Path) -> None:
    import agentdiff.diff.parse as parse_mod

    src = inspect.getsource(parse_mod.parse_unified_diff)
    assert "open(" not in src
    assert "subprocess" not in src
    assert "os." not in src
    assert "git" not in src

    for _, value in vars(parse_mod).items():
        if isinstance(value, types.ModuleType):
            module_name = value.__name__
            assert not module_name.startswith("agentdiff.store")
            assert not module_name.startswith("agentdiff.cli")
            assert not module_name.startswith("agentdiff.mcp")
            assert not module_name.startswith("agentdiff.tui")
            assert not module_name.startswith("textual")

    repo_root = Path(__file__).parents[2]
    env = dict(os.environ, PYTHONPATH=str(repo_root / "src"))
    script = (
        "from agentdiff.diff.parse import parse_unified_diff\n"
        f"change = parse_unified_diff({repr(BASIC)})\n"
        "print('ok')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


def test_r1_approval_revisions_created_at_unset() -> None:
    change = parse_unified_diff(BASIC)
    assert change.approval is None
    assert change.base_revision is None
    assert change.head_revision is None
    assert change.created_at is None


_EDGE_FIXTURES: list[tuple[str, list[FileDiff]]] = [
    (
        "new_file.patch",
        [
            FileDiff(
                path="new.txt",
                old_path=None,
                old_mode=None,
                new_mode="100644",
                is_binary=False,
                hunks=[
                    Hunk(
                        old_start=0,
                        old_count=0,
                        new_start=1,
                        new_count=3,
                        lines=[
                            Line(kind="add", old_no=None, new_no=1, text="line1"),
                            Line(kind="add", old_no=None, new_no=2, text="line2"),
                            Line(kind="add", old_no=None, new_no=3, text="line3"),
                        ],
                    )
                ],
            )
        ],
    ),
    (
        "deleted_file.patch",
        [
            FileDiff(
                path="old.txt",
                old_path=None,
                old_mode="100644",
                new_mode=None,
                is_binary=False,
                hunks=[
                    Hunk(
                        old_start=1,
                        old_count=3,
                        new_start=0,
                        new_count=0,
                        lines=[
                            Line(kind="del", old_no=1, new_no=None, text="line1"),
                            Line(kind="del", old_no=2, new_no=None, text="line2"),
                            Line(kind="del", old_no=3, new_no=None, text="line3"),
                        ],
                    )
                ],
            )
        ],
    ),
    (
        "rename.patch",
        [
            FileDiff(
                path="new.py",
                old_path="old.py",
                old_mode=None,
                new_mode=None,
                is_binary=False,
                hunks=[],
            )
        ],
    ),
    (
        "rename_modify.patch",
        [
            FileDiff(
                path="new.py",
                old_path="old.py",
                hunks=[
                    Hunk(
                        old_start=1,
                        old_count=2,
                        new_start=1,
                        new_count=2,
                        lines=[
                            Line(kind="del", old_no=1, new_no=None, text="a"),
                            Line(kind="add", old_no=None, new_no=1, text="a2"),
                            Line(kind="ctx", old_no=2, new_no=2, text="b"),
                        ],
                    )
                ],
            )
        ],
    ),
    (
        "mode_only.patch",
        [
            FileDiff(
                path="script.sh",
                old_path=None,
                old_mode="100644",
                new_mode="100755",
                is_binary=False,
                hunks=[],
            )
        ],
    ),
    (
        "binary.patch",
        [
            FileDiff(
                path="img.bin",
                old_path=None,
                old_mode=None,
                new_mode=None,
                is_binary=True,
                hunks=[],
            )
        ],
    ),
    (
        "no_newline.patch",
        [
            FileDiff(
                path="f.txt",
                hunks=[
                    Hunk(
                        old_start=1,
                        old_count=2,
                        new_start=1,
                        new_count=2,
                        lines=[
                            Line(kind="ctx", old_no=1, new_no=1, text="a"),
                            Line(kind="del", old_no=2, new_no=None, text="b"),
                            Line(kind="add", old_no=None, new_no=2, text="b2"),
                        ],
                    )
                ],
            )
        ],
    ),
    (
        "single_line.patch",
        [
            FileDiff(
                path="s.txt",
                hunks=[
                    Hunk(
                        old_start=1,
                        old_count=1,
                        new_start=1,
                        new_count=1,
                        lines=[
                            Line(kind="del", old_no=1, new_no=None, text="hello"),
                            Line(kind="add", old_no=None, new_no=1, text="world"),
                        ],
                    )
                ],
            )
        ],
    ),
    (
        "multiple_hunks.patch",
        [
            FileDiff(
                path="m.txt",
                hunks=[
                    Hunk(
                        old_start=1,
                        old_count=6,
                        new_start=1,
                        new_count=6,
                        lines=[
                            Line(kind="ctx", old_no=1, new_no=1, text="1"),
                            Line(kind="ctx", old_no=2, new_no=2, text="2"),
                            Line(kind="del", old_no=3, new_no=None, text="3"),
                            Line(kind="add", old_no=None, new_no=3, text="X3"),
                            Line(kind="ctx", old_no=4, new_no=4, text="4"),
                            Line(kind="ctx", old_no=5, new_no=5, text="5"),
                            Line(kind="ctx", old_no=6, new_no=6, text="6"),
                        ],
                    ),
                    Hunk(
                        old_start=19,
                        old_count=7,
                        new_start=19,
                        new_count=7,
                        lines=[
                            Line(kind="ctx", old_no=19, new_no=19, text="19"),
                            Line(kind="ctx", old_no=20, new_no=20, text="20"),
                            Line(kind="ctx", old_no=21, new_no=21, text="21"),
                            Line(kind="del", old_no=22, new_no=None, text="22"),
                            Line(kind="add", old_no=None, new_no=22, text="Y22"),
                            Line(kind="ctx", old_no=23, new_no=23, text="23"),
                            Line(kind="ctx", old_no=24, new_no=24, text="24"),
                            Line(kind="ctx", old_no=25, new_no=25, text="25"),
                        ],
                    ),
                ],
            )
        ],
    ),
    (
        "gnu_style.patch",
        [
            FileDiff(
                path="new.c",
                old_path="old.c",
                hunks=[
                    Hunk(
                        old_start=1,
                        old_count=1,
                        new_start=1,
                        new_count=1,
                        lines=[
                            Line(kind="del", old_no=1, new_no=None, text="x"),
                            Line(kind="add", old_no=None, new_no=1, text="x2"),
                        ],
                    )
                ],
            )
        ],
    ),
    (
        "format_patch.patch",
        [
            FileDiff(
                path="src/x.py",
                hunks=[
                    Hunk(
                        old_start=1,
                        old_count=1,
                        new_start=1,
                        new_count=1,
                        lines=[
                            Line(kind="del", old_no=1, new_no=None, text="y"),
                            Line(kind="add", old_no=None, new_no=1, text="y2"),
                        ],
                    )
                ],
            )
        ],
    ),
]


@pytest.mark.parametrize(
    "name,expected", _EDGE_FIXTURES, ids=[n for n, _ in _EDGE_FIXTURES]
)
def test_r5_edge_fixtures(name: str, expected: list[FileDiff]) -> None:
    change = parse_unified_diff(load_fixture(name))
    assert change.files == expected


_MALFORMED: list[tuple[str, str]] = [
    ("empty", ""),
    ("whitespace", "  \n\t\n  "),
    ("non-diff", "hello world\nthis is not a diff\n"),
    ("hunk-outside-file", "@@ -1,2 +1,2 @@\n a\n b\n"),
    ("missing-plus-plus-plus", "--- a/x\n"),
    ("missing-hunk-after-paths", "--- a/x\n+++ b/x\n"),
    ("bad-hunk-header", "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -x +y @@\n a\n"),
    (
        "truncated-hunk",
        "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1,5 +1,5 @@\n a\n b\n",
    ),
    (
        "count-mismatch",
        "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1,3 +1,2 @@\n a\n-b\n+c\n",
    ),
    (
        "bad-body-line",
        "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1,2 +1,2 @@\n a\n*bad\n",
    ),
    (
        "stray-no-newline-marker",
        "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1,1 +1,1 @@\n"
        "\\ No newline at end of file\n a\n",
    ),
    (
        "git-binary-patch-rejected",
        "diff --git a/x b/x\nGIT binary patch\nliteral 10\n...\n",
    ),
    (
        "combined-diff-rejected",
        "diff --cc src/x.c\nindex 111,222..333,444\n--- a/src/x.c\n+++ b/src/x.c\n"
        "@@@ -1,2 -1,2 +1,2 @@@\n",
    ),
    ("malformed-no-diff", load_malformed("no_diff.patch")),
    ("malformed-bad-hunk", load_malformed("bad_hunk.patch")),
    ("malformed-truncated-hunk", load_malformed("truncated_hunk.patch")),
    ("malformed-bad-body", load_malformed("bad_body.patch")),
]


@pytest.mark.parametrize("name,text", _MALFORMED, ids=[n for n, _ in _MALFORMED])
def test_r6_malformed_raises(name: str, text: str) -> None:
    with pytest.raises(DiffParseError):
        parse_unified_diff(text)


def test_r6_error_is_typed() -> None:
    with pytest.raises(DiffParseError) as excinfo:
        parse_unified_diff("junk")
    assert type(excinfo.value) is DiffParseError
    assert isinstance(excinfo.value, ValueError)


_WELL_FORMED_FIXTURE_NAMES = [
    "basic.patch",
    "new_file.patch",
    "deleted_file.patch",
    "rename.patch",
    "rename_modify.patch",
    "mode_only.patch",
    "binary.patch",
    "no_newline.patch",
    "single_line.patch",
    "multiple_hunks.patch",
    "gnu_style.patch",
    "format_patch.patch",
]
_MALFORMED_FIXTURE_NAMES = [
    "malformed/no_diff.patch",
    "malformed/bad_hunk.patch",
    "malformed/truncated_hunk.patch",
    "malformed/bad_body.patch",
]


def test_r8_fixtures_exist() -> None:
    root = Path(__file__).parent / "fixtures"
    for name in [*_WELL_FORMED_FIXTURE_NAMES, *_MALFORMED_FIXTURE_NAMES]:
        assert (root / name).is_file(), name


def test_r8_fixtures_are_static() -> None:
    root = Path(__file__).parent
    double_quoted = 'f"' + "diff --git"
    single_quoted = "f'" + "diff --git"
    for py in sorted(root.glob("test_*.py")):
        source = py.read_text(encoding="utf-8")
        assert double_quoted not in source
        assert single_quoted not in source
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "join"
            ):
                for arg in node.args:
                    assert "diff --git" not in ast.unparse(arg)


def _case_count(path: Path) -> int:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    total = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or not node.name.startswith("test_"):
            continue
        per_function = 1
        for decorator in node.decorator_list:
            if (
                isinstance(decorator, ast.Call)
                and getattr(decorator.func, "attr", None) == "parametrize"
            ):
                for arg in decorator.args:
                    if isinstance(arg, (ast.List, ast.Tuple)):
                        per_function = max(per_function, len(arg.elts))
        total += per_function
    return total


def test_r8_pure_string_tests_dominate() -> None:
    root = Path(__file__).parent
    pure = sum(
        _case_count(root / name) for name in ("test_parse.py", "test_serialize.py")
    )
    non_pure = sum(
        _case_count(root / name) for name in ("test_sources.py", "test_integration.py")
    )
    assert pure > non_pure


def test_r9_pydantic_single_runtime_dep() -> None:
    import tomllib

    pyproject = Path(__file__).parents[2] / "pyproject.toml"
    project = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]
    assert project["dependencies"] == ["pydantic>=2.0"]
    dev = project["optional-dependencies"]["dev"]
    assert any(dep.startswith("pytest") for dep in dev)
    assert any(dep.startswith("ruff") for dep in dev)
