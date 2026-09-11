from __future__ import annotations

import hashlib

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

_DIFFS: list[tuple[str, list[FileDiff]]] = [
    ("basic.patch", _BASIC_EXPECTED),
    *_EDGE_FIXTURES,
]


@pytest.mark.parametrize(
    "name,expected",
    _DIFFS,
    ids=[n for n, _ in _DIFFS],
)
def test_parses_diffs(name: str, expected: list[FileDiff]) -> None:
    change = parse_unified_diff(load_fixture(name))
    assert change.files == expected


def test_change_id() -> None:
    a = parse_unified_diff(BASIC)
    b = parse_unified_diff(BASIC)
    expected = "chg-" + hashlib.sha256(BASIC.encode("utf-8")).hexdigest()[:16]
    assert a.id == b.id
    assert a.id == expected
    assert a.id
    c = parse_unified_diff(BASIC.replace("ctx1", "ctx0"))
    assert a.id != c.id


def test_parse_keeps_approval_base_and_created_at_unset() -> None:
    change = parse_unified_diff(BASIC)
    assert change.approval is None
    assert change.base_revision is None
    assert change.created_at is None
    assert change.current is not None
    assert change.current.created_at is None


def test_change_identity_and_patch_content_id() -> None:
    from agentdiff.model import Version, stable_change_id

    assert stable_change_id("feat/x", "abc") == stable_change_id("feat/x", "abc")
    assert stable_change_id("feat/x", "abc").startswith("chg-")
    first = stable_change_id("feat/x", "abc")
    assert stable_change_id("feat/x", "def") != first
    assert stable_change_id("feat/y", "abc") != first
    assert stable_change_id(None, "abc") != first

    a = parse_unified_diff(BASIC)
    b = parse_unified_diff(BASIC)
    c = parse_unified_diff(load_fixture("single_line.patch"))

    assert isinstance(a.versions[0], Version)
    assert len(a.versions) == 1
    assert a.id == b.id
    assert a.id == f"chg-{a.versions[0].revision}"
    assert a.files == a.versions[0].files
    assert a.head_revision == a.versions[0].revision
    assert a.created_at is None
    assert c.id != a.id


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
def test_malformed_input_raises_parse_error(name: str, text: str) -> None:
    with pytest.raises(DiffParseError):
        parse_unified_diff(text)


def test_parse_error_is_typed_value_error() -> None:
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
