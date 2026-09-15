from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tests.tui.conftest import comment_factory, make_version

from agentdiff.anchor import (
    ThreadState,
    group_threads,
    is_resolved_thread,
    reopen_reply,
    resolution_reply,
    thread_last_author,
    thread_state,
    thread_state_of,
)
from agentdiff.model import Change, CommentState, Role

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


def test_thread_last_author_is_latest_member() -> None:
    root = comment_factory("c-root", revision="rev-1", role=Role.HUMAN, created_at=NOW)
    agent_reply = comment_factory(
        "c-a",
        revision="rev-1",
        in_reply_to="c-root",
        role=Role.AGENT,
        created_at=later(1),
    )
    human_reply = comment_factory(
        "c-h",
        revision="rev-1",
        in_reply_to="c-a",
        role=Role.HUMAN,
        created_at=later(2),
    )
    solo = comment_factory("c-solo", revision="rev-1", role=Role.AGENT, created_at=NOW)
    tie_x = comment_factory(
        "c-x", revision="rev-1", role=Role.HUMAN, created_at=later(3)
    )
    tie_y = comment_factory(
        "c-y",
        revision="rev-1",
        in_reply_to="c-x",
        role=Role.AGENT,
        created_at=later(3),
    )

    assert group_threads([root, agent_reply])[0].last_author is Role.AGENT
    assert group_threads([root, agent_reply, human_reply])[0].last_author is Role.HUMAN
    assert (
        thread_last_author(agent_reply, [root, agent_reply, human_reply]) is Role.HUMAN
    )
    assert group_threads([solo])[0].last_author is Role.AGENT
    assert group_threads([tie_x, tie_y])[0].last_author is Role.AGENT


def test_thread_last_author_follows_visible_tip() -> None:
    root = comment_factory("c-root", revision="rev-1", role=Role.HUMAN, created_at=NOW)
    closed_tip = comment_factory(
        "c-closed",
        revision="rev-1",
        in_reply_to="c-root",
        role=Role.AGENT,
        state=CommentState.CLOSED,
        created_at=later(1),
    )

    assert group_threads([root])[0].last_author is Role.HUMAN
    assert thread_last_author(root, [root]) is Role.HUMAN
    assert thread_last_author(root, [root, closed_tip]) is Role.AGENT


def test_reply_builders_stamp_role() -> None:
    change = Change(id="chg-s", versions=[make_version("rev-1", "basic.patch")])
    root = comment_factory("c-root", revision="rev-1")
    reopen_default = reopen_reply(
        root, change, text="why this way?", author="agentdiff"
    )
    reopen_agent = reopen_reply(
        root, change, text="note", author="reviewer", role=Role.AGENT
    )
    resolve_default = resolution_reply(root, change)
    resolve_human = resolution_reply(root, change, role=Role.HUMAN)

    assert reopen_default.role is Role.HUMAN
    assert reopen_default.state is CommentState.ACTIVE
    assert reopen_default.in_reply_to == "c-root"
    assert reopen_agent.role is Role.AGENT
    assert reopen_agent.author == "reviewer"
    assert resolve_default.role is Role.AGENT
    assert resolve_default.state is CommentState.RESOLVED
    assert resolve_default.author == "agent"
    assert resolve_human.role is Role.HUMAN
    assert resolve_human.state is CommentState.RESOLVED
