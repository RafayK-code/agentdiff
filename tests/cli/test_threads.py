from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from tests.tui.conftest import comment_factory, make_version

from agentdiff.cli import main
from agentdiff.model import Change, CommentState, LineRange, Side
from agentdiff.store import create_store

NOW = datetime(2020, 1, 1, tzinfo=timezone.utc)


def later(seconds: int) -> datetime:
    return NOW + timedelta(seconds=seconds)


@pytest.fixture
def shared_store(tmp_path: Path) -> tuple[Path, object]:
    root_dir = tmp_path / "store"
    store = create_store(root_dir)
    store.save_change(
        Change(id="chg-s", versions=[make_version("rev-1", "basic.patch")])
    )
    root = comment_factory(
        "c-root",
        change_id="chg-s",
        revision="rev-1",
        range=LineRange(side=Side.NEW, start=1, end=1),
        state=CommentState.ACTIVE,
        text="issue",
    )
    reply = comment_factory(
        "c-reply",
        change_id="chg-s",
        revision="rev-1",
        range=LineRange(side=Side.NEW, start=1, end=1),
        in_reply_to="c-root",
        state=CommentState.RESOLVED,
        text="resolved",
        created_at=later(1),
    )
    other = comment_factory(
        "c-other",
        change_id="chg-s",
        revision="rev-1",
        range=LineRange(side=Side.NEW, start=2, end=2),
        state=CommentState.ACTIVE,
        text="other",
    )
    store.add_comment(root)
    store.add_comment(reply)
    store.add_comment(other)
    return root_dir, store


def test_list_threads_groups_and_indents(
    capsys: pytest.CaptureFixture[str], shared_store: tuple[Path, object]
) -> None:
    root_dir, _ = shared_store

    rc = main(["list", "--change", "chg-s", "--threads", "--root", str(root_dir)])
    lines = capsys.readouterr().out.splitlines()

    assert rc == 0
    assert len(lines) == 3
    assert lines[0].startswith("[resolved] ")
    assert "c-root" in lines[0]
    assert "[ACTIVE]" in lines[0]
    assert lines[1].startswith("  ")
    assert not lines[1].startswith("   ")
    assert "c-reply" in lines[1]
    assert "[RESOLVED]" in lines[1]
    assert "in-reply-to=c-root" in lines[1]
    assert lines[2].startswith("[open] ")
    assert "c-other" in lines[2]


def test_list_default_output_unchanged(
    capsys: pytest.CaptureFixture[str], shared_store: tuple[Path, object]
) -> None:
    root_dir, _ = shared_store

    rc = main(["list", "--change", "chg-s", "--root", str(root_dir)])
    lines = capsys.readouterr().out.splitlines()

    assert rc == 0
    assert [line.split()[0] for line in lines] == ["c-root", "c-reply", "c-other"]
    assert all(not line.startswith(("[", " ")) for line in lines)
    assert "in-reply-to=c-root" in lines[1]


def test_list_thread_state_shows_whole_thread(
    capsys: pytest.CaptureFixture[str], shared_store: tuple[Path, object]
) -> None:
    root_dir, _ = shared_store

    rc_r = main(
        [
            "list",
            "--change",
            "chg-s",
            "--thread-state",
            "resolved",
            "--root",
            str(root_dir),
        ]
    )
    resolved_out = capsys.readouterr().out.splitlines()
    rc_o = main(
        ["list", "--change", "chg-s", "--thread-state", "open", "--root", str(root_dir)]
    )
    open_out = capsys.readouterr().out.splitlines()

    assert rc_r == 0
    assert rc_o == 0
    assert len(resolved_out) == 2
    assert resolved_out[0].startswith("[resolved] ")
    assert "c-root" in resolved_out[0]
    assert "c-reply" in resolved_out[1]
    assert "c-other" not in "\n".join(resolved_out)
    assert len(open_out) == 1
    assert open_out[0].startswith("[open] ")
    assert "c-other" in open_out[0]
    assert "c-root" not in open_out[0]


def test_list_thread_state_closed_and_empty(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    root_dir2 = tmp_path / "store2"
    store2 = create_store(root_dir2)
    store2.save_change(
        Change(id="chg-s", versions=[make_version("rev-1", "basic.patch")])
    )
    croot = comment_factory(
        "c-croot",
        change_id="chg-s",
        revision="rev-1",
        range=LineRange(side=Side.NEW, start=3, end=3),
        state=CommentState.ACTIVE,
        text="c-root",
    )
    cclose = comment_factory(
        "c-cc",
        change_id="chg-s",
        revision="rev-1",
        range=LineRange(side=Side.NEW, start=3, end=3),
        in_reply_to="c-croot",
        state=CommentState.CLOSED,
        text="c-reply",
        created_at=later(1),
    )
    store2.add_comment(croot)
    store2.add_comment(cclose)

    rc_all = main(
        [
            "list",
            "--change",
            "chg-s",
            "--thread-state",
            "closed",
            "--include-closed",
            "--root",
            str(root_dir2),
        ]
    )
    closed_out = capsys.readouterr().out.splitlines()
    rc_none = main(
        [
            "list",
            "--change",
            "chg-s",
            "--thread-state",
            "resolved",
            "--root",
            str(root_dir2),
        ]
    )
    none_out = capsys.readouterr().out

    assert rc_all == 0
    assert len(closed_out) == 2
    assert closed_out[0].startswith("[closed] ")
    assert "c-croot" in closed_out[0]
    assert "c-cc" in closed_out[1]
    assert rc_none == 0
    assert none_out == "No threads.\n"


def test_list_state_vs_thread_state_compose(
    capsys: pytest.CaptureFixture[str], shared_store: tuple[Path, object]
) -> None:
    root_dir, _ = shared_store

    rc_ta = main(
        [
            "list",
            "--change",
            "chg-s",
            "--threads",
            "--state",
            "active",
            "--root",
            str(root_dir),
        ]
    )
    active_out = capsys.readouterr().out.splitlines()
    rc_tr = main(
        [
            "list",
            "--change",
            "chg-s",
            "--threads",
            "--state",
            "resolved",
            "--root",
            str(root_dir),
        ]
    )
    own_out = capsys.readouterr().out.splitlines()
    rc_ts = main(
        [
            "list",
            "--change",
            "chg-s",
            "--thread-state",
            "resolved",
            "--root",
            str(root_dir),
        ]
    )
    thread_out = capsys.readouterr().out.splitlines()

    assert rc_ta == 0
    assert rc_tr == 0
    assert rc_ts == 0
    assert len(active_out) == 2
    assert active_out[0].startswith("[open] ")
    assert "c-root" in active_out[0]
    assert active_out[1].startswith("[open] ")
    assert "c-other" in active_out[1]
    assert len(own_out) == 1
    assert own_out[0].startswith("[resolved] ")
    assert "c-reply" in own_out[0]
    assert "c-root" not in own_out[0]
    assert len(thread_out) == 2
    assert "c-root" in thread_out[0]
    assert "c-reply" in thread_out[1]
