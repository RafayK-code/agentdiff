from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tests.tui.conftest import comment_factory

from agentdiff.anchor import (
    ThreadState,
    group_threads,
    is_resolved_thread,
    thread_state,
    thread_state_of,
)
from agentdiff.model import CommentState

NOW = datetime(2020, 1, 1, tzinfo=timezone.utc)


def later(seconds: int) -> datetime:
    return NOW + timedelta(seconds=seconds)


def test_group_threads_members_order_and_thread_order() -> None:
    a_root = comment_factory("c-a1", revision="rev-1", text="a-root", created_at=NOW)
    a_reply = comment_factory(
        "c-a2",
        revision="rev-1",
        in_reply_to="c-a1",
        text="a-reply",
        created_at=later(2),
    )
    b_root = comment_factory(
        "c-b1", revision="rev-1", text="b-root", created_at=later(1)
    )
    orphan = comment_factory(
        "c-orphan",
        revision="rev-1",
        in_reply_to="c-missing",
        text="orphan",
        created_at=later(3),
    )
    tie_x = comment_factory("c-x", revision="rev-1", text="x", created_at=later(5))
    tie_y = comment_factory(
        "c-y", revision="rev-1", in_reply_to="c-x", text="y", created_at=later(5)
    )

    threads = group_threads([a_reply, b_root, a_root, orphan, tie_y, tie_x])

    assert [t.root.id for t in threads] == ["c-a1", "c-b1", "c-orphan", "c-x"]
    assert [t.root_id for t in threads] == ["c-a1", "c-b1", "c-orphan", "c-x"]
    assert tuple(m.id for m in threads[0].members) == ("c-a1", "c-a2")
    assert tuple(m.id for m in threads[0].replies) == ("c-a2",)
    assert threads[0].root.id == "c-a1"
    assert tuple(m.id for m in threads[1].members) == ("c-b1",)
    assert threads[1].replies == ()
    assert tuple(m.id for m in threads[2].members) == ("c-orphan",)
    assert tuple(m.id for m in threads[3].members) == ("c-x", "c-y")


def test_thread_state_derived_from_latest_member() -> None:
    r_root = comment_factory(
        "c-r", revision="rev-1", state=CommentState.ACTIVE, created_at=NOW
    )
    r_reply = comment_factory(
        "c-rr",
        revision="rev-1",
        in_reply_to="c-r",
        state=CommentState.RESOLVED,
        created_at=later(1),
    )
    o_root = comment_factory(
        "c-o", revision="rev-1", state=CommentState.RESOLVED, created_at=NOW
    )
    o_res = comment_factory(
        "c-os",
        revision="rev-1",
        in_reply_to="c-o",
        state=CommentState.RESOLVED,
        created_at=later(1),
    )
    o_reopen = comment_factory(
        "c-or",
        revision="rev-1",
        in_reply_to="c-os",
        state=CommentState.ACTIVE,
        created_at=later(2),
    )
    c_root = comment_factory(
        "c-c", revision="rev-1", state=CommentState.ACTIVE, created_at=NOW
    )
    c_close = comment_factory(
        "c-cc",
        revision="rev-1",
        in_reply_to="c-c",
        state=CommentState.CLOSED,
        created_at=later(1),
    )

    resolved = group_threads([r_root, r_reply])[0]
    reopened = group_threads([o_root, o_res, o_reopen])[0]
    closed = group_threads([c_root, c_close])[0]

    assert ThreadState.OPEN.value == "open"
    assert ThreadState.RESOLVED.value == "resolved"
    assert ThreadState.CLOSED.value == "closed"
    assert thread_state_of(CommentState.ACTIVE) is ThreadState.OPEN
    assert thread_state_of(CommentState.RESOLVED) is ThreadState.RESOLVED
    assert thread_state_of(CommentState.CLOSED) is ThreadState.CLOSED
    assert resolved.state is ThreadState.RESOLVED
    assert reopened.state is ThreadState.OPEN
    assert closed.state is ThreadState.CLOSED
    assert thread_state(r_root, [r_root, r_reply]) is ThreadState.RESOLVED
    assert thread_state(r_reply, [r_root, r_reply]) is ThreadState.RESOLVED
    assert is_resolved_thread(r_root, [r_root, r_reply]) is True
    assert is_resolved_thread(o_reopen, [o_root, o_res, o_reopen]) is False
    assert is_resolved_thread(c_root, [c_root, c_close]) is False
