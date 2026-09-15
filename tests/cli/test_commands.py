from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from tests.diff.conftest import load_fixture
from tests.tui.conftest import comment_factory, make_version

from agentdiff.cli import main
from agentdiff.diff.parse import parse_unified_diff
from agentdiff.model import (
    Change,
    Comment,
    CommentState,
    LineRange,
    Side,
    Version,
)
from agentdiff.store import create_store


def _basic_files() -> list:
    return parse_unified_diff(load_fixture("basic.patch")).files


def test_cli_write_commands(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    root = tmp_path / "store"
    store = create_store(root)
    store.save_change(
        Change(
            id="chg-s",
            branch="feat/x",
            versions=[Version(revision="rev-1", files=_basic_files())],
        )
    )

    rc = main(
        [
            "add",
            "src/foo.py",
            "--change",
            "chg-s",
            "--lines",
            "2-2",
            "--side",
            "new",
            "--message",
            "look here",
            "--author",
            "bob",
            "--root",
            str(root),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.err == ""
    comments = store.list_comments("chg-s")
    assert len(comments) == 1
    added = comments[0]
    assert added.text == "look here"
    assert added.author == "bob"
    assert added.revision == "rev-1"
    assert added.range == LineRange(side=Side.NEW, start=2, end=2)
    assert added.in_reply_to is None
    assert added.state is CommentState.ACTIVE
    added_id = added.id

    rc = main(["resolve", added_id, "--root", str(root)])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.err == ""
    # resolving is a comment: the original is untouched and a RESOLVED reply
    # is appended, exactly like the TUI path (one shared core function).
    assert store.get_comment(added_id).state is CommentState.ACTIVE
    resolved_reply = next(
        c for c in store.list_comments("chg-s") if c.in_reply_to == added_id
    )
    assert resolved_reply.state is CommentState.RESOLVED
    assert resolved_reply.text == "resolved"
    assert captured.out.strip() == resolved_reply.id

    rc = main(["reopen", added_id, "--root", str(root)])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.err == ""
    # the reopen reply attaches to the thread tip (the RESOLVED reply), not the root
    reply = next(
        c
        for c in store.list_comments("chg-s")
        if c.in_reply_to == resolved_reply.id and c.state is CommentState.ACTIVE
    )
    assert reply.revision == "rev-1"
    assert store.get_comment(added_id).state is CommentState.ACTIVE
    reply_id = reply.id

    # close takes a thread root and closes the whole thread
    rc = main(["close", added_id, "--root", str(root)])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.err == ""
    assert store.get_comment(added_id).state is CommentState.CLOSED
    assert store.get_comment(reply_id).state is CommentState.CLOSED
    assert reply_id not in [c.id for c in store.list_comments("chg-s")]
    assert reply_id in [c.id for c in store.list_comments("chg-s", include_closed=True)]


def test_cli_close_closes_whole_thread(tmp_path: Path) -> None:
    root_dir = tmp_path / "store"
    store = create_store(root_dir)
    store.save_change(
        Change(id="chg-s", versions=[make_version("rev-1", "basic.patch")])
    )
    root = comment_factory(
        "c-root",
        change_id="chg-s",
        revision="rev-1",
        range=LineRange(side=Side.NEW, start=2, end=2),
        in_reply_to=None,
    )
    reply = comment_factory(
        "c-reply",
        change_id="chg-s",
        revision="rev-1",
        range=LineRange(side=Side.NEW, start=2, end=2),
        in_reply_to="c-root",
    )
    other = comment_factory(
        "c-other",
        change_id="chg-s",
        revision="rev-1",
        range=LineRange(side=Side.NEW, start=1, end=1),
        in_reply_to=None,
    )
    store.add_comment(root)
    store.add_comment(reply)
    store.add_comment(other)

    rc = main(["close", "c-root", "--root", str(root_dir)])

    assert rc == 0
    assert store.get_comment("c-root").state is CommentState.CLOSED
    assert store.get_comment("c-reply").state is CommentState.CLOSED
    assert store.get_comment("c-other").state is CommentState.ACTIVE
    assert [c.id for c in store.list_comments("chg-s")] == ["c-other"]
    assert {c.id for c in store.list_comments("chg-s", include_closed=True)} == {
        "c-root",
        "c-reply",
        "c-other",
    }


def test_cli_read_surface(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    root = tmp_path / "store"
    store = create_store(root)
    early = datetime(2024, 1, 1, tzinfo=timezone.utc)
    late = datetime(2024, 6, 1, tzinfo=timezone.utc)
    old = Change(
        id="chg-old",
        branch="feat/x",
        created_at=early,
        versions=[Version(revision="old-rev", files=_basic_files(), created_at=early)],
    )
    new = Change(
        id="chg-new",
        branch="feat/x",
        created_at=late,
        versions=[Version(revision="new-rev", files=_basic_files(), created_at=late)],
    )
    store.save_change(old)
    store.save_change(new)

    comment = Comment(
        id="c-new",
        change_id="chg-new",
        revision="new-rev",
        file="src/foo.py",
        range=LineRange(side=Side.NEW, start=2, end=2),
        text="hi",
        author="alice",
        state=CommentState.ACTIVE,
        created_at=late,
        updated_at=late,
    )
    store.add_comment(comment)

    rc = main(["changes", "--root", str(root)])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.err == ""
    for needle in ("chg-old", "chg-new", "old-rev", "new-rev"):
        assert needle in captured.out

    rc = main(["export", "--branch", "feat/x", "--format", "json", "--root", str(root)])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.err == ""
    doc = json.loads(captured.out)
    assert doc["change"]["id"] == "chg-new"
    assert doc["change"]["current_revision"] == "new-rev"

    rc = main(
        [
            "list",
            "--change",
            "chg-new",
            "--revision",
            "new-rev",
            "--root",
            str(root),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.err == ""
    assert "c-new" in captured.out


def test_resolve_attaches_to_thread_tip(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    root = tmp_path / "store"
    store = create_store(root)
    store.save_change(
        Change(
            id="chg-s",
            branch="feat/x",
            versions=[Version(revision="rev-1", files=_basic_files())],
        )
    )
    store.add_comment(
        comment_factory(
            "c-root",
            revision="rev-1",
            range=LineRange(side=Side.NEW, start=1, end=1),
        )
    )
    store.add_comment(
        comment_factory(
            "c-reply",
            revision="rev-1",
            range=LineRange(side=Side.NEW, start=1, end=1),
            in_reply_to="c-root",
            created_at=datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=1),
        )
    )

    rc = main(["resolve", "c-root", "--root", str(root)])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.err == ""

    resolution = next(
        comment
        for comment in store.list_comments("chg-s")
        if comment.state is CommentState.RESOLVED
    )
    # the resolution attaches to the thread tip, not the id that was passed
    assert resolution.in_reply_to == "c-reply"


def test_thread_commands_reject_non_root(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    root_dir = tmp_path / "store"
    store = create_store(root_dir)
    store.save_change(
        Change(id="chg-s", versions=[make_version("rev-1", "basic.patch")])
    )
    store.add_comment(comment_factory("c-root", revision="rev-1"))
    store.add_comment(
        comment_factory(
            "c-reply",
            revision="rev-1",
            in_reply_to="c-root",
            created_at=datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=1),
        )
    )
    for command in ("resolve", "reopen", "close"):
        rc = main([command, "c-reply", "--root", str(root_dir)])
        captured = capsys.readouterr()
        assert rc == 1
        assert "not a thread root" in captured.err


def test_add_reply_inherits_parent_anchor(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    root = tmp_path / "store"
    store = create_store(root)
    store.save_change(
        Change(id="chg-s", versions=[make_version("rev-1", "basic.patch")])
    )
    parent = comment_factory(
        "c-parent",
        change_id="chg-s",
        revision="rev-1",
        range=LineRange(side=Side.NEW, start=2, end=2),
    )
    store.add_comment(parent)

    rc = main(
        [
            "add",
            "src/foo.py",
            "--in-reply-to",
            "c-parent",
            "--message",
            "why?",
            "--role",
            "agent",
            "--root",
            str(root),
        ]
    )
    reply_id = capsys.readouterr().out.strip()
    reply = store.get_comment(reply_id)

    assert rc == 0
    assert reply.in_reply_to == "c-parent"
    assert reply.range == parent.range
    assert reply.file == parent.file
    assert reply.anchor_snapshot == ["added"]

    rc_lines = main(
        [
            "add",
            "src/foo.py",
            "--in-reply-to",
            "c-parent",
            "--lines",
            "3-3",
            "--message",
            "moved",
            "--root",
            str(root),
        ]
    )
    moved = store.get_comment(capsys.readouterr().out.strip())

    assert rc_lines == 0
    assert moved.range == LineRange(side=Side.NEW, start=3, end=3)
