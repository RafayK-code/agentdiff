from __future__ import annotations

from datetime import timedelta

from tests.diff.conftest import load_fixture
from tests.tui.conftest import NOW, comment_factory

from agentdiff.anchor import group_threads
from agentdiff.diff.parse import parse_unified_diff
from agentdiff.model import CommentState, LineRange, Role, Side
from agentdiff.tui.comments import (
    AnchorBox,
    CommentAnnotation,
    CommentKind,
    ThreadKind,
    ThreadMarker,
    adjacent_thread,
    anchor_boxes,
    marker_row,
    thread_index,
    thread_kind,
    thread_markers,
    thread_order,
)
from agentdiff.tui.render import FileContent, make_diff_view, render_view


def later(n: int):
    return NOW + timedelta(seconds=n)


def _basic_render():
    file = parse_unified_diff(load_fixture("basic.patch")).files[0]
    return render_view(
        make_diff_view(
            file,
            header="[modified] src/foo.py",
            content=FileContent(side=Side.NEW, lines=("ctx1", "added", "ctx2")),
        )
    )


def _navigation_order():
    files = ["src/foo.py", "new.txt"]
    comments = [
        comment_factory(
            "c-b",
            revision="rev-2",
            file="src/foo.py",
            range=LineRange(side=Side.NEW, start=5, end=5),
        ),
        comment_factory(
            "c-a",
            revision="rev-2",
            file="new.txt",
            range=LineRange(side=Side.NEW, start=2, end=2),
        ),
        comment_factory(
            "c-c",
            revision="rev-2",
            file="src/foo.py",
            range=LineRange(side=Side.NEW, start=1, end=1),
        ),
        comment_factory(
            "c-d", revision="rev-2", file="src/foo.py", range=None, drifted=True
        ),
        comment_factory(
            "c-c2",
            revision="rev-2",
            file="src/foo.py",
            range=LineRange(side=Side.NEW, start=1, end=1),
            created_at=later(1),
        ),
    ]
    return thread_order(files, comments, revision="rev-2")


def test_thread_order_sorts_by_file_then_anchor() -> None:
    order = _navigation_order()

    assert [ref.root.id for ref in order] == ["c-d", "c-c", "c-c2", "c-b", "c-a"]
    assert [ref.file_index for ref in order] == [0, 0, 0, 0, 1]
    assert [ref.file for ref in order] == [
        "src/foo.py",
        "src/foo.py",
        "src/foo.py",
        "src/foo.py",
        "new.txt",
    ]
    assert order[0].root.id == "c-d"


def test_thread_order_excludes_closed_stale_and_unknown_files() -> None:
    files = ["src/foo.py"]
    comments = [
        comment_factory(
            "c-active",
            revision="rev-2",
            file="src/foo.py",
            range=LineRange(side=Side.NEW, start=1, end=1),
        ),
        comment_factory(
            "c-closed",
            revision="rev-2",
            file="src/foo.py",
            state=CommentState.CLOSED,
            range=LineRange(side=Side.NEW, start=2, end=2),
        ),
        comment_factory(
            "c-stale",
            revision="rev-1",
            file="src/foo.py",
            range=LineRange(side=Side.NEW, start=1, end=1),
        ),
        comment_factory(
            "c-ghost",
            revision="rev-2",
            file="ghost.py",
            range=LineRange(side=Side.NEW, start=1, end=1),
        ),
    ]

    scoped = thread_order(files, comments, revision="rev-2")
    unscoped = thread_order(files, comments)

    assert [ref.root.id for ref in scoped] == ["c-active"]
    assert [ref.root.id for ref in unscoped] == ["c-active", "c-stale"]


def test_adjacent_thread_steps_and_clamps() -> None:
    order = _navigation_order()
    empty = thread_order(["src/foo.py"], [])

    assert thread_index(order, "c-c2") == 2
    assert thread_index(order, "missing") is None
    assert thread_index(order, None) is None

    assert adjacent_thread(order, "c-c2", +1).root.id == "c-b"
    assert adjacent_thread(order, "c-c2", -1).root.id == "c-c"
    assert adjacent_thread(order, "c-d", -1).root.id == "c-d"
    assert adjacent_thread(order, "c-a", +1).root.id == "c-a"
    assert adjacent_thread(order, None, +1).root.id == "c-d"
    assert adjacent_thread(order, None, -1).root.id == "c-a"
    assert adjacent_thread(empty, None, +1) is None
    assert adjacent_thread(empty, "c-x", -1) is None


def test_anchor_boxes_use_per_comment_kind() -> None:
    rendered = _basic_render()
    root = CommentAnnotation(
        comment=comment_factory(
            "c-root",
            revision="rev-2",
            role=Role.HUMAN,
            range=LineRange(side=Side.NEW, start=1, end=1),
        ),
        depth=0,
    )
    reply = CommentAnnotation(
        comment=comment_factory(
            "c-reply",
            revision="rev-2",
            role=Role.AGENT,
            range=LineRange(side=Side.NEW, start=3, end=3),
            in_reply_to="c-root",
        ),
        depth=1,
        reply=True,
    )

    assert anchor_boxes(rendered, (root, reply)) == (
        AnchorBox(start=2, end=2, kind=CommentKind.HUMAN),
        AnchorBox(start=5, end=5, kind=CommentKind.AGENT),
    )


def test_thread_kind_derives_from_conversation_state() -> None:
    pending_thread = group_threads(
        [
            comment_factory("c-p", revision="rev-1", role=Role.HUMAN, created_at=NOW),
            comment_factory(
                "c-p2",
                revision="rev-1",
                in_reply_to="c-p",
                role=Role.AGENT,
                created_at=later(1),
            ),
        ]
    )[0]
    resolved_thread = group_threads(
        [
            comment_factory("c-r", revision="rev-1", role=Role.HUMAN, created_at=NOW),
            comment_factory(
                "c-r2",
                revision="rev-1",
                in_reply_to="c-r",
                role=Role.AGENT,
                state=CommentState.RESOLVED,
                created_at=later(1),
            ),
        ]
    )[0]
    awaiting_agent_thread = group_threads(
        [comment_factory("c-h", revision="rev-1", role=Role.HUMAN)]
    )[0]
    awaiting_you_thread = group_threads(
        [
            comment_factory("c-y", revision="rev-1", role=Role.HUMAN, created_at=NOW),
            comment_factory(
                "c-y2",
                revision="rev-1",
                in_reply_to="c-y",
                role=Role.AGENT,
                created_at=later(1),
            ),
        ]
    )[0]

    assert thread_kind(pending_thread, {"c-p2"}) is ThreadKind.PENDING
    assert thread_kind(pending_thread) is ThreadKind.AWAITING_YOU
    assert thread_kind(resolved_thread) is ThreadKind.RESOLVED
    assert thread_kind(awaiting_agent_thread) is ThreadKind.AWAITING_AGENT
    assert thread_kind(awaiting_you_thread) is ThreadKind.AWAITING_YOU
    assert ThreadKind.AWAITING_AGENT.value == "awaiting_agent"
    assert ThreadKind.AWAITING_YOU.value == "awaiting_you"


def test_marker_row_is_proportional_and_clamped() -> None:
    assert marker_row(0, 10, 5) == 0
    assert marker_row(9, 10, 5) == 4
    assert marker_row(3, 9, 5) == 1
    assert marker_row(5, 11, 6) == 2
    assert marker_row(100, 10, 5) == 4
    assert marker_row(0, 1, 5) == 0
    assert marker_row(0, 0, 5) == 0
    assert marker_row(4, 10, 1) == 0


def test_thread_markers_carry_position_and_thread_color() -> None:
    markers = thread_markers(
        [(0, ThreadKind.AWAITING_YOU, "c-a"), (9, ThreadKind.RESOLVED, "c-b")],
        total_rows=10,
        height=5,
    )
    empty = thread_markers([], total_rows=10, height=5)

    assert markers == (
        ThreadMarker(row=0, kind=ThreadKind.AWAITING_YOU, root="c-a"),
        ThreadMarker(row=4, kind=ThreadKind.RESOLVED, root="c-b"),
    )
    assert empty == ()
