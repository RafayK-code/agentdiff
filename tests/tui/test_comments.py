from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from tests.diff.conftest import load_fixture
from tests.tui.conftest import NOW, comment_factory, make_version

from agentdiff.anchor import (
    RESOLVE_AUTHOR,
    is_resolve_comment,
    is_resolved_thread,
    resolution_reply,
    thread_members,
    thread_root,
    thread_root_id,
    thread_tip,
)
from agentdiff.diff.parse import parse_unified_diff
from agentdiff.model import (
    Change,
    CommentState,
    FileDiff,
    Hunk,
    Line,
    LineRange,
    Role,
    Side,
    Version,
)
from agentdiff.store import StoreError, create_store
from agentdiff.tui.comments import (
    DRIFTED_NOTE,
    AnchorBox,
    CommentAnnotation,
    CommentKind,
    DraftKind,
    EditorDraft,
    FileCommentCounts,
    PendingBuffer,
    Selection,
    anchor_boxes,
    annotate,
    annotation_kind,
    build_comment_view,
    comment_counts,
    draft_to_comment,
    extend_to,
    flush_comments,
    inline_annotations,
    move_anchor,
    new_draft,
    pending_count,
    put_pending,
    remove_pending,
    reopen_draft,
    reply_draft,
    resolve_side,
    select_line,
    selection_range,
    set_draft_text,
    side_compatible,
    step_to_compatible,
    thread_rows,
)
from agentdiff.tui.render import (
    CellKind,
    FileContent,
    RowKind,
    make_diff_view,
    render_view,
)


def later(n: int):
    return NOW + timedelta(seconds=n)


def _basic_change() -> Change:
    return Change(
        id="chg-s",
        versions=[
            make_version("rev-1", "basic.patch"),
            make_version("rev-2", "basic.patch", "new_file.patch"),
        ],
    )


def test_comment_view_partitions_and_threads() -> None:
    change = _basic_change()
    root = comment_factory(
        "c-root", revision="rev-2", range=LineRange(side=Side.NEW, start=1, end=1)
    )
    reply = comment_factory(
        "c-reply",
        revision="rev-2",
        range=LineRange(side=Side.NEW, start=2, end=2),
        in_reply_to="c-root",
    )
    orphan = comment_factory(
        "c-orphan",
        revision="rev-2",
        range=LineRange(side=Side.NEW, start=2, end=2),
        in_reply_to="c-gone",
    )
    stale = comment_factory(
        "c-stale", revision="rev-1", range=LineRange(side=Side.NEW, start=2, end=2)
    )
    resolved = comment_factory(
        "c-resolved",
        revision="rev-1",
        state=CommentState.RESOLVED,
        range=LineRange(side=Side.NEW, start=2, end=2),
    )
    closed = comment_factory(
        "c-closed",
        revision="rev-2",
        state=CommentState.CLOSED,
        range=LineRange(side=Side.NEW, start=2, end=2),
    )

    comments = [root, reply, orphan, stale, resolved, closed]
    view = build_comment_view(comments, change)

    assert {t.comment.id for t in view.inline} == {"c-root", "c-orphan"}
    assert {t.comment.id: t for t in view.inline}["c-root"].replies == (reply,)
    assert [t.replies for t in view.inline if t.comment.id == "c-orphan"] == [()]
    # rev-1 comments stay on rev-1 and do not leak onto the rev-2 view
    assert [c.id for c in view.resolved] == []
    assert [c.id for c in view.hidden] == ["c-closed"]

    rev1 = build_comment_view(comments, change, "rev-1")
    assert {t.comment.id for t in rev1.inline} == {"c-stale"}
    assert [c.id for c in rev1.resolved] == ["c-resolved"]


def test_resolve_appends_resolved_reply() -> None:
    change = _basic_change()
    original = comment_factory(
        "c-issue",
        revision="rev-2",
        range=LineRange(side=Side.NEW, start=2, end=2),
        text="this is an issue",
        author="reviewer",
    )

    reply = resolution_reply(original, change, now=NOW)

    assert reply is not original
    assert reply.id != original.id and reply.id.startswith("c-")
    assert reply.text == "resolved"
    assert reply.author == RESOLVE_AUTHOR == "agent"
    assert reply.state is CommentState.RESOLVED
    assert reply.in_reply_to == original.id
    assert reply.revision == "rev-2"
    assert reply.change_id == "chg-s"
    assert reply.file == "src/foo.py" and reply.range == original.range
    assert reply.anchor_snapshot == ["added"]
    assert reply.created_at == NOW and reply.updated_at == NOW
    assert original.state is CommentState.ACTIVE
    assert original.text == "this is an issue"
    assert is_resolve_comment(reply) is True
    assert is_resolve_comment(original) is False


def test_resolved_thread_last_member_and_reopen() -> None:
    root = comment_factory(
        "c-root",
        revision="rev-2",
        range=LineRange(side=Side.NEW, start=1, end=1),
        text="issue",
        created_at=NOW,
    )
    resolved = comment_factory(
        "c-res",
        revision="rev-2",
        state=CommentState.RESOLVED,
        in_reply_to="c-root",
        range=LineRange(side=Side.NEW, start=1, end=1),
        text="resolved",
        author="agent",
        created_at=later(1),
    )
    reopened = comment_factory(
        "c-new",
        revision="rev-2",
        state=CommentState.ACTIVE,
        in_reply_to="c-res",
        range=LineRange(side=Side.NEW, start=1, end=1),
        text="still broken",
        created_at=later(2),
    )
    auto = comment_factory(
        "c-auto",
        revision="rev-1",
        state=CommentState.RESOLVED,
        range=LineRange(side=Side.NEW, start=1, end=1),
        text="old",
        created_at=NOW,
    )

    assert is_resolve_comment(root) is False
    assert is_resolve_comment(resolved) is True
    assert is_resolve_comment(reopened) is False
    assert is_resolved_thread(root, [root]) is False
    assert is_resolved_thread(root, [root, resolved]) is True
    assert is_resolved_thread(resolved, [root, resolved]) is True
    assert is_resolved_thread(auto, [auto]) is True
    assert is_resolved_thread(root, [root, resolved, reopened]) is False
    assert resolved.state is CommentState.RESOLVED
    assert [c.id for c in [root, resolved, reopened]] == ["c-root", "c-res", "c-new"]


def test_thread_helpers_root_tip_members_and_rows() -> None:
    root = comment_factory("c-1", revision="rev-2", text="root", created_at=NOW)
    mid = comment_factory(
        "c-2", revision="rev-2", in_reply_to="c-1", text="mid", created_at=later(1)
    )
    tip = comment_factory(
        "c-3", revision="rev-2", in_reply_to="c-2", text="tip", created_at=later(2)
    )
    chain = [root, mid, tip]
    tie_a = comment_factory("c-a", revision="rev-2", text="a", created_at=NOW)
    tie_b = comment_factory(
        "c-b", revision="rev-2", in_reply_to="c-a", text="b", created_at=NOW
    )
    unrelated = comment_factory("c-x", revision="rev-2", text="x")
    comment_rows = {10: root, 12: mid, 14: tip}

    assert thread_root(mid, chain + [unrelated]) is root
    assert thread_root(root, chain) is root
    assert thread_root(tip, chain) is root
    assert thread_root_id(mid, chain) == "c-1"
    assert thread_tip(root, chain) is tip
    assert thread_tip(mid, chain) is tip
    assert thread_tip(tip, chain) is tip
    assert thread_members(mid, chain) == (root, mid, tip)
    assert thread_members(root, chain) == (root, mid, tip)
    assert thread_tip(tie_a, [tie_a, tie_b]) is tie_b
    assert thread_members(tie_a, [tie_a, tie_b]) == (tie_a, tie_b)
    assert thread_root(unrelated, chain + [unrelated]) is unrelated
    assert thread_members(unrelated, chain + [unrelated]) == (unrelated,)
    assert thread_rows(comment_rows, mid, chain) == (10, 12, 14)
    assert thread_rows(comment_rows, root, chain) == (10, 12, 14)
    assert thread_rows(comment_rows, tip, chain) == (10, 12, 14)
    assert thread_rows(comment_rows, unrelated, chain + [unrelated]) == ()


def test_reopen_draft_reanchors_or_drifts_and_attaches_to_tip() -> None:
    v1 = make_version("rev-1", "basic.patch")
    shifted = FileDiff(
        path="src/foo.py",
        hunks=[
            Hunk(
                old_start=1,
                old_count=3,
                new_start=1,
                new_count=4,
                lines=[
                    Line(kind="ctx", old_no=1, new_no=1, text="ctx1"),
                    Line(kind="del", old_no=2, new_no=None, text="removed"),
                    Line(kind="add", old_no=None, new_no=2, text="inserted"),
                    Line(kind="add", old_no=None, new_no=3, text="added"),
                    Line(kind="ctx", old_no=3, new_no=4, text="ctx2"),
                ],
            )
        ],
    )
    v2 = Version(revision="rev-2", files=[shifted])
    change = Change(id="chg-s", versions=[v1, v2])
    root = comment_factory(
        "c-r",
        revision="rev-1",
        state=CommentState.RESOLVED,
        range=LineRange(side=Side.NEW, start=2, end=2),
        text="revisit",
        anchor_snapshot=["added"],
        created_at=NOW,
    )
    tip = comment_factory(
        "c-t",
        revision="rev-2",
        state=CommentState.ACTIVE,
        in_reply_to="c-r",
        range=LineRange(side=Side.NEW, start=3, end=3),
        text="still open",
        created_at=later(1),
    )
    lost = comment_factory(
        "c-l",
        revision="rev-1",
        state=CommentState.RESOLVED,
        range=LineRange(side=Side.NEW, start=2, end=2),
        text="revisit",
        anchor_snapshot=["vanished text"],
    )

    d_tip = reopen_draft(tip, [root, tip], change, author="alice")
    d_root = reopen_draft(root, [root, tip], change, author="alice")
    d_lost = reopen_draft(lost, [lost], change, author="alice")
    c_tip = draft_to_comment(
        set_draft_text(d_tip, "please revisit"), change, author="alice", now=NOW
    )

    assert d_tip.kind is DraftKind.REOPEN
    assert d_tip.in_reply_to == "c-t"
    assert d_root.in_reply_to == "c-t"
    assert d_tip.quoted == "revisit" and d_root.quoted == "revisit"
    assert d_tip.drifted is False
    assert d_tip.anchor == LineRange(side=Side.NEW, start=3, end=3)
    assert d_tip.file == "src/foo.py"
    assert d_lost.drifted is True and d_lost.anchor is None
    assert d_lost.file == "src/foo.py"
    assert d_lost.in_reply_to == "c-l"
    assert c_tip.in_reply_to == "c-t"
    assert c_tip.revision == "rev-2"
    assert c_tip.state is CommentState.ACTIVE
    assert root.state is CommentState.RESOLVED


def _basic_render():
    file = parse_unified_diff(load_fixture("basic.patch")).files[0]
    return render_view(
        make_diff_view(
            file,
            header="[modified] src/foo.py",
            content=FileContent(side=Side.NEW, lines=("ctx1", "added", "ctx2")),
        )
    )


def _shifted_render():
    file = FileDiff(
        path="src/foo.py",
        hunks=[
            Hunk(
                old_start=1,
                old_count=3,
                new_start=1,
                new_count=4,
                lines=[
                    Line(kind="ctx", old_no=1, new_no=1, text="top"),
                    Line(kind="del", old_no=2, new_no=None, text="gone"),
                    Line(kind="add", old_no=None, new_no=2, text="inserted"),
                    Line(kind="add", old_no=None, new_no=3, text="extra"),
                    Line(kind="ctx", old_no=3, new_no=4, text="bottom"),
                ],
            )
        ],
    )
    return render_view(make_diff_view(file, header="[modified] src/foo.py"))


def test_select_line_collapses_to_point_and_carries_side() -> None:
    base = Selection()
    point = select_line(base, 5)
    old_point = select_line(base, 4, Side.OLD)
    cleared = select_line(old_point, None, None)

    assert base.side is None and base.anchor is None and base.cursor is None
    assert point.anchor == 5 and point.cursor == 5 and point.side is None
    assert (
        old_point.anchor == 4 and old_point.cursor == 4 and old_point.side is Side.OLD
    )
    assert cleared.anchor is None and cleared.cursor is None and cleared.side is None


def test_side_compatible_truth_table() -> None:
    assert side_compatible(None, None) is True
    assert side_compatible(None, Side.OLD) is True
    assert side_compatible(None, Side.NEW) is True
    assert side_compatible(Side.OLD, None) is True
    assert side_compatible(Side.OLD, Side.OLD) is True
    assert side_compatible(Side.OLD, Side.NEW) is False
    assert side_compatible(Side.NEW, None) is True
    assert side_compatible(Side.NEW, Side.OLD) is False
    assert side_compatible(Side.NEW, Side.NEW) is True


def test_resolve_side_defaults_neutral_to_new() -> None:
    assert resolve_side(None) is Side.NEW
    assert resolve_side(Side.OLD) is Side.OLD
    assert resolve_side(Side.NEW) is Side.NEW


def test_extend_to_locks_first_color_and_refuses_cross_color() -> None:
    grey = select_line(Selection(), 2, None)
    grey_extends = extend_to(grey, 5, None)
    locks_old = extend_to(grey, 5, Side.OLD)
    refused = extend_to(locks_old, 8, Side.NEW)
    locks_new = extend_to(select_line(Selection(), 9, None), 12, Side.NEW)

    assert grey_extends.side is None
    assert grey_extends.anchor == 2 and grey_extends.cursor == 5
    assert locks_old.side is Side.OLD
    assert locks_old.anchor == 2 and locks_old.cursor == 5
    assert refused == locks_old
    assert locks_new.side is Side.NEW
    assert locks_new.anchor == 9 and locks_new.cursor == 12


def test_step_to_compatible_skips_opposite_color() -> None:
    shifted = _shifted_render()

    assert step_to_compatible(shifted, 3, +1, Side.OLD) == 6
    assert step_to_compatible(shifted, 5, +1, Side.OLD) == 6
    assert step_to_compatible(shifted, 3, +1, Side.NEW) == 4
    assert step_to_compatible(shifted, 6, -1, Side.NEW) == 5
    assert step_to_compatible(shifted, 6, -1, Side.OLD) == 3
    assert step_to_compatible(shifted, 6, +1, Side.OLD) is None


def test_selection_range_resolves_neutral_and_locks_old() -> None:
    shifted = _shifted_render()
    red_point = selection_range(shifted, select_line(Selection(), 3, Side.OLD))
    neutral = selection_range(shifted, select_line(Selection(), 6, None))
    grey_then_red = selection_range(
        shifted, extend_to(select_line(Selection(), 6, None), 3, Side.OLD)
    )
    red_then_grey = selection_range(
        shifted, extend_to(select_line(Selection(), 3, Side.OLD), 6, None)
    )
    skipped = selection_range(
        shifted,
        extend_to(
            select_line(Selection(), 3, Side.OLD),
            step_to_compatible(shifted, 3, +1, Side.OLD),
            None,
        ),
    )
    empty = selection_range(shifted, Selection())

    assert red_point == LineRange(side=Side.OLD, start=2, end=2)
    assert neutral == LineRange(side=Side.NEW, start=4, end=4)
    assert grey_then_red == LineRange(side=Side.OLD, start=2, end=3)
    assert red_then_grey == LineRange(side=Side.OLD, start=2, end=3)
    assert skipped == LineRange(side=Side.OLD, start=2, end=3)
    assert empty is None


def test_draft_to_comment_persists_old_side_snapshot() -> None:
    change = Change(id="chg-s", versions=[make_version("rev-1", "basic.patch")])
    draft = new_draft("src/foo.py", LineRange(side=Side.OLD, start=2, end=2))
    draft = set_draft_text(draft, "this line was removed")
    comment = draft_to_comment(draft, change, author="bob", now=NOW)

    assert comment.range == LineRange(side=Side.OLD, start=2, end=2)
    assert comment.range.side is Side.OLD
    assert comment.anchor_snapshot == ["removed"]
    assert comment.revision == "rev-1"


def test_old_side_comment_renders_at_removed_line() -> None:
    rendered = _basic_render()
    comment = comment_factory(
        "c-old", revision="rev-1", range=LineRange(side=Side.OLD, start=2, end=2)
    )
    annotation = CommentAnnotation(comment=comment, depth=0)

    result = annotate(rendered, (annotation,))
    boxes = anchor_boxes(rendered, (annotation,))

    assert result.comment_rows == {4: comment}
    assert result.rendered.lines[3].kind is RowKind.CHANGE
    assert result.rendered.lines[3].columns[0].kind is CellKind.DEL
    assert boxes == (AnchorBox(start=3, end=3, kind=CommentKind.ACTIVE),)


def test_editor_draft_confirms_and_moves_anchor() -> None:
    change = _basic_change()
    anchor = LineRange(side=Side.NEW, start=2, end=2)
    empty = new_draft("src/foo.py", anchor)
    draft = set_draft_text(empty, "look here")
    new_comment = draft_to_comment(draft, change, author="bob", now=NOW)
    parent = comment_factory("c-parent", revision="rev-2", range=anchor, text="parent")
    reply = set_draft_text(reply_draft(parent), "why?")
    reply_comment = draft_to_comment(reply, change, author="alice", now=NOW)
    valid = [1, 2, 3, 4]
    moved = move_anchor(new_draft("src/foo.py", anchor), +1, valid)
    clamped = move_anchor(
        new_draft("src/foo.py", LineRange(side=Side.NEW, start=4, end=4)), +1, valid
    )
    drifted = EditorDraft(
        file="src/foo.py",
        kind=DraftKind.REOPEN,
        anchor=LineRange(side=Side.NEW, start=1, end=1),
        text="t",
        drifted=True,
    )
    fixed = move_anchor(drifted, +1, valid)

    assert empty.kind is DraftKind.NEW and empty.text == ""
    assert new_comment.revision == "rev-2"
    assert new_comment.state is CommentState.ACTIVE
    assert new_comment.range == anchor
    assert new_comment.in_reply_to is None
    assert new_comment.author == "bob"
    assert new_comment.drifted is False
    assert new_comment.anchor_snapshot == ["added"]
    assert new_comment.id.startswith("c-")
    assert reply.kind is DraftKind.REPLY
    assert reply.in_reply_to == "c-parent" and reply.anchor == parent.range
    assert reply_comment.in_reply_to == "c-parent"
    assert reply_comment.revision == "rev-2"
    assert reply_comment.state is CommentState.ACTIVE
    assert moved.anchor == LineRange(side=Side.NEW, start=3, end=3)
    assert clamped.anchor == LineRange(side=Side.NEW, start=4, end=4)
    assert fixed.anchor == LineRange(side=Side.NEW, start=2, end=2)
    assert fixed.drifted is False


def test_pending_buffer_add_replace_remove() -> None:
    empty = PendingBuffer()
    one = comment_factory(
        "p1",
        revision="rev-2",
        range=LineRange(side=Side.NEW, start=1, end=1),
        text="one",
    )
    two = comment_factory(
        "p2",
        revision="rev-2",
        range=LineRange(side=Side.NEW, start=2, end=2),
        text="two",
    )
    one_edited = comment_factory(
        "p1",
        revision="rev-2",
        range=LineRange(side=Side.NEW, start=2, end=2),
        text="one-edited",
    )
    b2 = put_pending(put_pending(empty, one), two)
    b3 = put_pending(b2, one_edited)
    b4 = remove_pending(b3, "p2")
    b5 = remove_pending(b4, "missing")

    assert pending_count(empty) == 0
    assert pending_count(b2) == 2
    assert [c.id for c in b2.items] == ["p1", "p2"]
    assert pending_count(b3) == 2
    assert [c.id for c in b3.items] == ["p1", "p2"]
    assert b3.items[0].text == "one-edited"
    assert pending_count(b4) == 1
    assert [c.id for c in b4.items] == ["p1"]
    assert pending_count(b5) == 1


def test_flush_comments_writes_in_order_and_keeps_remainder(tmp_path: Path) -> None:
    store = create_store(tmp_path)
    change = Change(id="chg-s", versions=[make_version("rev-1", "basic.patch")])
    store.save_change(change)
    p1 = comment_factory(
        "p1",
        change_id="chg-s",
        revision="rev-1",
        range=LineRange(side=Side.NEW, start=1, end=1),
        text="one",
    )
    p2 = comment_factory(
        "p2",
        change_id="chg-s",
        revision="rev-1",
        range=LineRange(side=Side.NEW, start=2, end=2),
        text="two",
    )
    p3 = comment_factory(
        "p3",
        change_id="chg-s",
        revision="rev-1",
        range=LineRange(side=Side.NEW, start=3, end=3),
        text="three",
    )
    buffer = put_pending(put_pending(put_pending(PendingBuffer(), p1), p2), p3)

    ok = flush_comments(put_pending(put_pending(PendingBuffer(), p1), p2), store)
    assert ok.error is None and ok.remaining == ()
    assert [c.id for c in ok.written] == ["p1", "p2"]
    assert [c.id for c in store.list_comments("chg-s")] == ["p1", "p2"]

    class FailingStore:
        def __init__(self, *, raise_on: str) -> None:
            self.raise_on = raise_on
            self.attempted: list[str] = []
            self.written: list[str] = []

        def add_comment(self, comment) -> None:
            self.attempted.append(comment.id)
            if comment.id == self.raise_on:
                raise StoreError("disk full")
            self.written.append(comment.id)

    failing = FailingStore(raise_on="p2")
    partial = flush_comments(buffer, failing)
    assert [c.id for c in partial.written] == ["p1"]
    assert [c.id for c in partial.remaining] == ["p2", "p3"]
    assert partial.error is not None and "disk full" in partial.error
    assert failing.attempted == ["p1", "p2"]
    assert failing.written == ["p1"]


def test_inline_annotations_thread_resolved_reply_and_filter() -> None:
    change = _basic_change()
    root = comment_factory(
        "c-root",
        revision="rev-2",
        range=LineRange(side=Side.NEW, start=1, end=1),
        text="this is an issue",
        author="reviewer",
        created_at=NOW,
    )
    resolved_reply = comment_factory(
        "c-res",
        revision="rev-2",
        state=CommentState.RESOLVED,
        in_reply_to="c-root",
        range=LineRange(side=Side.NEW, start=1, end=1),
        text="resolved",
        author="agent",
        created_at=later(1),
    )
    drifted = comment_factory("c-drift", revision="rev-2", range=None, drifted=True)
    view = build_comment_view([root, resolved_reply, drifted], change)
    pending = put_pending(
        put_pending(
            PendingBuffer(),
            comment_factory(
                "p1",
                revision="rev-2",
                file="src/foo.py",
                range=LineRange(side=Side.NEW, start=3, end=3),
            ),
        ),
        comment_factory(
            "p2",
            revision="rev-2",
            file="new.txt",
            range=LineRange(side=Side.NEW, start=1, end=1),
        ),
    )

    anns = inline_annotations(view, pending, "src/foo.py")

    assert [a.comment.id for a in anns] == ["c-root", "c-res", "c-drift", "p1"]
    assert {a.comment.id: (a.depth, a.resolved, a.reply, a.pending) for a in anns} == {
        "c-root": (0, False, False, False),
        "c-res": (1, True, True, False),
        "c-drift": (0, False, False, False),
        "p1": (0, False, False, True),
    }
    assert [a.note for a in anns if a.comment.id == "c-drift"] == [
        "location not found in patch"
    ]
    assert inline_annotations(view, PendingBuffer(), "new.txt") == ()


def test_annotate_splices_rows_and_adjusts_hunk_starts() -> None:
    file = parse_unified_diff(load_fixture("basic.patch")).files[0]
    rendered = render_view(
        make_diff_view(
            file,
            header="[modified] src/foo.py",
            content=FileContent(side=Side.NEW, lines=("ctx1", "added", "ctx2")),
        )
    )
    root = comment_factory(
        "c-root", revision="rev-2", range=LineRange(side=Side.NEW, start=1, end=1)
    )
    reply = comment_factory(
        "c-reply",
        revision="rev-2",
        range=LineRange(side=Side.NEW, start=2, end=2),
        in_reply_to="c-root",
    )
    drifted = comment_factory("c-drift", revision="rev-2", range=None, drifted=True)
    annotations = (
        CommentAnnotation(comment=root, depth=0),
        CommentAnnotation(comment=reply, depth=1, reply=True),
        CommentAnnotation(comment=drifted, depth=0, note="location not found in patch"),
    )

    result = annotate(rendered, annotations)
    noop = annotate(rendered, ())

    assert len(result.rendered.lines) == len(rendered.lines) + 3
    assert {c.id for c in result.comment_rows.values()} == {
        "c-root",
        "c-reply",
        "c-drift",
    }
    assert all(
        result.rendered.lines[i].kind is RowKind.COMMENT for i in result.comment_rows
    )
    assert result.comment_rows[1] == drifted
    assert result.rendered.lines[1].kind is RowKind.COMMENT
    idx = {c.id: i for i, c in result.comment_rows.items()}
    assert idx["c-root"] > 1 and idx["c-reply"] > idx["c-root"]
    assert "\u21b3" in result.rendered.lines[idx["c-reply"]].text
    assert "\u21b3" not in result.rendered.lines[idx["c-root"]].text
    assert result.pending == frozenset()
    assert result.rendered.hunk_starts == (2,)
    assert noop.rendered.lines == rendered.lines
    assert noop.rendered.hunk_starts == rendered.hunk_starts
    assert noop.comment_rows == {}


def test_anchor_boxes_merge_precedence_and_gaps() -> None:
    file = parse_unified_diff(load_fixture("basic.patch")).files[0]
    rendered = render_view(
        make_diff_view(
            file,
            header="[modified] src/foo.py",
            content=FileContent(side=Side.NEW, lines=("ctx1", "added", "ctx2")),
        )
    )
    active = CommentAnnotation(
        comment=comment_factory(
            "c-1", revision="rev-2", range=LineRange(side=Side.NEW, start=1, end=2)
        ),
        depth=0,
    )
    pending = CommentAnnotation(
        comment=comment_factory(
            "p1", revision="rev-2", range=LineRange(side=Side.NEW, start=2, end=2)
        ),
        depth=0,
        pending=True,
    )
    resolved = CommentAnnotation(
        comment=comment_factory(
            "c-r",
            revision="rev-2",
            state=CommentState.RESOLVED,
            range=LineRange(side=Side.NEW, start=3, end=3),
        ),
        depth=1,
        resolved=True,
        reply=True,
    )
    drifted = CommentAnnotation(
        comment=comment_factory("c-d", revision="rev-2", range=None, drifted=True),
        depth=0,
        note=DRIFTED_NOTE,
    )
    separate = (
        CommentAnnotation(
            comment=comment_factory(
                "c-a", revision="rev-2", range=LineRange(side=Side.NEW, start=1, end=1)
            ),
            depth=0,
        ),
        CommentAnnotation(
            comment=comment_factory(
                "c-b", revision="rev-2", range=LineRange(side=Side.NEW, start=3, end=3)
            ),
            depth=0,
        ),
    )

    assert anchor_boxes(rendered, (active, pending, resolved, drifted)) == (
        AnchorBox(start=2, end=5, kind=CommentKind.PENDING),
    )
    assert anchor_boxes(rendered, (active,)) == (
        AnchorBox(start=2, end=4, kind=CommentKind.ACTIVE),
    )
    assert anchor_boxes(rendered, separate) == (
        AnchorBox(start=2, end=2, kind=CommentKind.ACTIVE),
        AnchorBox(start=5, end=5, kind=CommentKind.ACTIVE),
    )
    assert anchor_boxes(rendered, ()) == ()


def test_comment_counts_are_conversation_level() -> None:
    change = _basic_change()
    active_root = comment_factory(
        "c-a",
        revision="rev-2",
        file="src/foo.py",
        range=LineRange(side=Side.NEW, start=1, end=1),
        created_at=NOW,
    )
    active_reply = comment_factory(
        "c-ar",
        revision="rev-2",
        file="src/foo.py",
        range=LineRange(side=Side.NEW, start=1, end=1),
        in_reply_to="c-a",
        created_at=later(1),
    )
    resolved_root = comment_factory(
        "c-r",
        revision="rev-2",
        file="src/foo.py",
        state=CommentState.RESOLVED,
        range=LineRange(side=Side.NEW, start=2, end=2),
        created_at=NOW,
    )
    resolved_reply = comment_factory(
        "c-rr",
        revision="rev-2",
        file="src/foo.py",
        state=CommentState.RESOLVED,
        range=LineRange(side=Side.NEW, start=2, end=2),
        in_reply_to="c-r",
        created_at=later(1),
    )
    plain_resolved = comment_factory(
        "c-s",
        revision="rev-2",
        file="src/foo.py",
        state=CommentState.RESOLVED,
        range=LineRange(side=Side.NEW, start=3, end=3),
        created_at=NOW,
    )
    other = comment_factory(
        "c-n",
        revision="rev-1",
        file="new.txt",
        state=CommentState.RESOLVED,
        range=LineRange(side=Side.NEW, start=1, end=1),
        created_at=NOW,
    )
    view = build_comment_view(
        [
            active_root,
            active_reply,
            resolved_root,
            resolved_reply,
            plain_resolved,
            other,
        ],
        change,
    )
    pending = put_pending(
        put_pending(
            PendingBuffer(),
            comment_factory(
                "p1",
                revision="rev-2",
                file="src/foo.py",
                range=LineRange(side=Side.NEW, start=4, end=4),
                created_at=later(2),
            ),
        ),
        comment_factory(
            "p2",
            revision="rev-2",
            file="src/foo.py",
            range=LineRange(side=Side.NEW, start=2, end=2),
            in_reply_to="c-r",
            created_at=later(3),
        ),
    )

    counts = comment_counts(view, pending)

    assert counts["src/foo.py"] == FileCommentCounts(
        draft=2, resolved=1, human_last=1, agent_last=0
    )
    # rev-1 comments are scoped out of the rev-2 view, so new.txt has no counts
    assert counts.get("new.txt", FileCommentCounts()) == FileCommentCounts()


def test_draft_authors_human() -> None:
    change = Change(id="chg-s", versions=[make_version("rev-1", "basic.patch")])
    root = comment_factory("c-root", revision="rev-1")
    draft = set_draft_text(
        new_draft("src/foo.py", LineRange(side=Side.NEW, start=1, end=1)), "hi"
    )

    default = draft_to_comment(draft, change, now=NOW)
    reply = draft_to_comment(reply_draft(root), change, now=NOW)
    explicit = draft_to_comment(
        draft, change, author="agentdiff", role=Role.AGENT, now=NOW
    )

    assert default.role is Role.HUMAN
    assert default.author == "reviewer"
    assert reply.role is Role.HUMAN
    assert explicit.role is Role.AGENT
    assert explicit.author == "agentdiff"


def test_annotation_kind_precedence() -> None:
    c = comment_factory("c-1", revision="rev-1")
    pending = CommentAnnotation(comment=c, pending=True, last_author=Role.AGENT)
    resolved = CommentAnnotation(comment=c, resolved=True, last_author=Role.HUMAN)
    both = CommentAnnotation(
        comment=c, pending=True, resolved=True, last_author=Role.HUMAN
    )
    human_last = CommentAnnotation(comment=c, last_author=Role.HUMAN)
    agent_last = CommentAnnotation(comment=c, last_author=Role.AGENT)
    bare = CommentAnnotation(comment=c)

    assert annotation_kind(pending) is CommentKind.PENDING
    assert annotation_kind(resolved) is CommentKind.RESOLVED
    assert annotation_kind(both) is CommentKind.PENDING
    assert annotation_kind(human_last) is CommentKind.HUMAN_LAST
    assert annotation_kind(agent_last) is CommentKind.AGENT_LAST
    assert annotation_kind(bare) is CommentKind.ACTIVE
    assert CommentKind.HUMAN_LAST.value == "human_last"
    assert CommentKind.AGENT_LAST.value == "agent_last"


def test_inline_annotations_carry_thread_last_author() -> None:
    change = Change(id="chg-s", versions=[make_version("rev-1", "basic.patch")])
    root = comment_factory("c-root", revision="rev-1", role=Role.HUMAN, created_at=NOW)
    agent_reply = comment_factory(
        "c-reply",
        revision="rev-1",
        in_reply_to="c-root",
        role=Role.AGENT,
        created_at=later(1),
    )
    view = build_comment_view([root, agent_reply], change)

    anns = inline_annotations(view, PendingBuffer(), "src/foo.py")
    pending_human = put_pending(
        PendingBuffer(),
        comment_factory(
            "p-1",
            revision="rev-1",
            in_reply_to="c-root",
            role=Role.HUMAN,
            created_at=later(2),
        ),
    )
    anns_pending = inline_annotations(view, pending_human, "src/foo.py")

    assert {a.comment.id: a.last_author for a in anns} == {
        "c-root": Role.AGENT,
        "c-reply": Role.AGENT,
    }
    assert {a.comment.id: (a.last_author, a.pending) for a in anns_pending} == {
        "c-root": (Role.HUMAN, False),
        "c-reply": (Role.HUMAN, False),
        "p-1": (Role.HUMAN, True),
    }


def test_comment_counts_split_by_last_responder() -> None:
    change = Change(id="chg-s", versions=[make_version("rev-1", "basic.patch")])
    p_root = comment_factory("c-p", revision="rev-1", role=Role.HUMAN, created_at=NOW)
    p_reply = comment_factory(
        "c-p2",
        revision="rev-1",
        in_reply_to="c-p",
        role=Role.AGENT,
        created_at=later(1),
    )
    h_root = comment_factory("c-h", revision="rev-1", role=Role.HUMAN, created_at=NOW)
    r_root = comment_factory("c-r", revision="rev-1", role=Role.HUMAN, created_at=NOW)
    r_reply = comment_factory(
        "c-r2",
        revision="rev-1",
        in_reply_to="c-r",
        role=Role.AGENT,
        state=CommentState.RESOLVED,
        created_at=later(1),
    )
    view = build_comment_view([p_root, p_reply, h_root, r_root, r_reply], change)
    pending = put_pending(
        PendingBuffer(),
        comment_factory(
            "p-h",
            revision="rev-1",
            in_reply_to="c-h",
            role=Role.HUMAN,
            created_at=later(2),
        ),
    )

    assert comment_counts(view, PendingBuffer())["src/foo.py"] == FileCommentCounts(
        draft=0, resolved=1, human_last=1, agent_last=1
    )
    assert comment_counts(view, pending)["src/foo.py"] == FileCommentCounts(
        draft=1, resolved=1, human_last=0, agent_last=1
    )
