from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tests.tui.conftest import comment_factory, make_version

from agentdiff.model import Change, CommentState
from agentdiff.tui.comments import (
    FileCommentCounts,
    PendingBuffer,
    build_comment_view,
    comment_counts,
    put_pending,
)

NOW = datetime(2020, 1, 1, tzinfo=timezone.utc)


def later(seconds: int) -> datetime:
    return NOW + timedelta(seconds=seconds)


def test_comment_counts_use_derived_thread_state() -> None:
    v1 = make_version("rev-1", "basic.patch")
    change = Change(id="chg-s", versions=[v1])
    root = comment_factory(
        "c-root",
        revision="rev-1",
        file="src/foo.py",
        state=CommentState.ACTIVE,
        created_at=NOW,
    )
    resolved_reply = comment_factory(
        "c-res",
        revision="rev-1",
        file="src/foo.py",
        in_reply_to="c-root",
        state=CommentState.RESOLVED,
        created_at=later(1),
    )
    other = comment_factory(
        "c-other",
        revision="rev-1",
        file="src/foo.py",
        state=CommentState.ACTIVE,
        created_at=NOW,
    )
    view = build_comment_view([root, resolved_reply, other], change)
    pending = put_pending(
        PendingBuffer(),
        comment_factory(
            "p-1",
            revision="rev-1",
            file="src/foo.py",
            in_reply_to="c-root",
            state=CommentState.ACTIVE,
            created_at=later(2),
        ),
    )

    counts = comment_counts(view, PendingBuffer())
    with_pending = comment_counts(view, pending)

    assert counts["src/foo.py"] == FileCommentCounts(draft=0, resolved=1, unresolved=1)
    assert with_pending["src/foo.py"] == FileCommentCounts(
        draft=1, resolved=0, unresolved=1
    )
