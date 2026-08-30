from __future__ import annotations

from tests.export.conftest import comment_factory

from agentdiff.export import export_markdown
from agentdiff.model import Change, CommentState, FileDiff, LineRange, Side


def test_markdown_header_and_trailing_newline(
    approved_change, mixed_comments: list[object]
) -> None:
    out = export_markdown(approved_change, mixed_comments)
    assert out.startswith("# Change chg-01\n\n")
    assert out.endswith("\n")
    assert not out.endswith("\n\n")


def test_markdown_file_sections(approved_change, mixed_comments: list[object]) -> None:
    out = export_markdown(approved_change, mixed_comments)
    for file in approved_change.files:
        assert out.count(f"## {file.path}") == 1

    change = Change(id="chg-x", files=[FileDiff(path="a.py"), FileDiff(path="b.py")])
    out = export_markdown(change, [])
    assert "## a.py" in out
    assert "## b.py" in out
    assert out.startswith("# Change chg-x\n")

    change = Change(
        id="chg-x",
        files=[FileDiff(path="aaa.txt"), FileDiff(path="zzz.txt")],
    )
    comments = [
        comment_factory(id="c-1", file="aaa.txt"),
        comment_factory(id="c-2", file="zzz.txt"),
    ]
    out = export_markdown(change, comments)
    assert out.index("## aaa.txt") < out.index("## zzz.txt")


def test_markdown_comment_formatting() -> None:
    change = Change(id="chg-01", files=[FileDiff(path="src/foo.py")])
    comment = comment_factory(
        id="c-001",
        file="src/foo.py",
        text="Rename this",
        author="alice",
        range=LineRange(side=Side.NEW, start=2, end=2),
    )
    out = export_markdown(change, [comment])
    assert "- c-001: Rename this (NEW 2-2) [alice, ACTIVE]" in out

    change = Change(id="chg-x", files=[FileDiff(path="a.txt")])
    comment = comment_factory(
        id="c-1", file="a.txt", range=LineRange(side=Side.OLD, start=1, end=3)
    )
    out = export_markdown(change, [comment])
    assert "(OLD 1-3)" in out

    comment = comment_factory(id="c-1", file="a.txt", range=None)
    out = export_markdown(change, [comment])
    assert "(file-level)" in out

    comments = [
        comment_factory(id="c-1", file="a.txt", author="bob"),
        comment_factory(
            id="c-2", file="a.txt", author="bob", state=CommentState.RESOLVED
        ),
        comment_factory(
            id="c-3", file="a.txt", author="bob", state=CommentState.DRIFTED
        ),
    ]
    out = export_markdown(change, comments)
    assert "[bob, ACTIVE]" in out
    assert "[bob, RESOLVED]" in out
    assert "[bob, DRIFTED]" in out

    c2 = comment_factory(id="c-2", file="a.txt", text="second")
    c1 = comment_factory(id="c-1", file="a.txt", text="first")
    out = export_markdown(change, [c2, c1])
    assert out.index("c-2") < out.index("c-1")

    orphan = comment_factory(id="c-o", file="orphan.py", text="lost")
    out = export_markdown(change, [orphan])
    assert "## a.txt" in out
    assert "## orphan.py" in out
    assert out.index("## a.txt") < out.index("## orphan.py")
    assert "c-o" in out
