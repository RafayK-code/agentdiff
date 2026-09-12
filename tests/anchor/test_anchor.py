from __future__ import annotations

from datetime import datetime, timezone

from tests.diff.conftest import load_fixture

from agentdiff.anchor import reanchor, reanchor_thread, reopen_reply
from agentdiff.diff.parse import parse_unified_diff
from agentdiff.model import (
    Change,
    Comment,
    CommentState,
    FileDiff,
    Hunk,
    Line,
    LineRange,
    Side,
    Version,
)

_CREATED = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _comment(
    *,
    revision: str = "rev-1",
    file: str = "src/foo.py",
    line_range: LineRange | None,
    snapshot: list[str] | None = None,
    state: CommentState = CommentState.ACTIVE,
    id: str = "c",
) -> Comment:
    return Comment(
        id=id,
        change_id="chg-s",
        revision=revision,
        file=file,
        range=line_range,
        text="t",
        author="a",
        state=state,
        created_at=_CREATED,
        updated_at=_CREATED,
        anchor_snapshot=snapshot if snapshot is not None else [],
    )


def _new_side_file(path: str, lines: list[str]) -> FileDiff:
    numbered = [
        Line(kind="ctx", old_no=index, new_no=index, text=text)
        for index, text in enumerate(lines, start=1)
    ]
    return FileDiff(
        path=path,
        hunks=[
            Hunk(
                old_start=1,
                old_count=len(numbered),
                new_start=1,
                new_count=len(numbered),
                lines=numbered,
            )
        ],
    )


def _v1() -> Version:
    return Version(
        revision="rev-1", files=parse_unified_diff(load_fixture("basic.patch")).files
    )


def test_reanchor_exact_normalized_and_missing() -> None:
    v1 = _v1()
    comment = _comment(
        line_range=LineRange(side=Side.NEW, start=1, end=3),
        snapshot=["  ctx1 ", "added", "ctx2"],
    )
    assert reanchor(comment, v1) == LineRange(side=Side.NEW, start=1, end=3)

    v2 = Version(
        revision="rev-2",
        files=[
            FileDiff(
                path="src/foo.py",
                hunks=[
                    Hunk(
                        old_start=10,
                        old_count=2,
                        new_start=10,
                        new_count=3,
                        lines=[
                            Line(kind="ctx", old_no=10, new_no=10, text="ctx1"),
                            Line(kind="add", old_no=None, new_no=11, text="added"),
                            Line(kind="ctx", old_no=11, new_no=12, text="ctx2"),
                        ],
                    )
                ],
            )
        ],
    )
    assert reanchor(comment, v2) == LineRange(side=Side.NEW, start=10, end=12)

    no_range = _comment(line_range=None, snapshot=["ctx1", "added", "ctx2"])
    assert reanchor(no_range, v1) is None

    empty_snapshot = _comment(
        line_range=LineRange(side=Side.NEW, start=1, end=1), snapshot=[]
    )
    assert reanchor(empty_snapshot, v1) is None

    dissimilar = _comment(
        line_range=LineRange(side=Side.NEW, start=1, end=1),
        snapshot=["totally", "different", "words"],
    )
    assert reanchor(dissimilar, v1) is None


def test_reanchor_fuzzy_threshold() -> None:
    version = Version(
        revision="rev-1",
        files=[
            _new_side_file(
                "src/foo.py",
                [
                    "import os",
                    "extract this block into a helper",
                    "return value",
                ],
            )
        ],
    )
    near = _comment(
        line_range=LineRange(side=Side.NEW, start=2, end=2),
        snapshot=["extract this block into a helpr"],
    )
    assert reanchor(near, version) == LineRange(side=Side.NEW, start=2, end=2)

    unrelated = _comment(
        line_range=LineRange(side=Side.NEW, start=2, end=2),
        snapshot=["completely unrelated sentence here"],
    )
    assert reanchor(unrelated, version) is None


def test_reopen_reply() -> None:
    v1 = _v1()
    v2 = Version(
        revision="rev-2",
        files=[
            FileDiff(
                path="src/foo.py",
                hunks=[
                    Hunk(
                        old_start=1,
                        old_count=1,
                        new_start=1,
                        new_count=3,
                        lines=[
                            Line(kind="ctx", old_no=1, new_no=1, text="ctx1"),
                            Line(kind="add", old_no=None, new_no=2, text="inserted"),
                            Line(kind="add", old_no=None, new_no=3, text="added"),
                        ],
                    )
                ],
            )
        ],
    )
    change = Change(id="chg-s", versions=[v1, v2])

    ranged = _comment(
        revision="rev-1",
        line_range=LineRange(side=Side.NEW, start=2, end=2),
        snapshot=["added"],
        state=CommentState.RESOLVED,
        id="c-ranged",
    )
    lost = _comment(
        revision="rev-1",
        line_range=LineRange(side=Side.NEW, start=2, end=2),
        snapshot=["vanished text"],
        state=CommentState.RESOLVED,
        id="c-lost",
    )
    file_level = _comment(
        revision="rev-1",
        line_range=None,
        state=CommentState.RESOLVED,
        id="c-file",
    )

    ranged_reply = reopen_reply(ranged, change, text="please revisit", author="alice")
    assert ranged_reply.revision == "rev-2"
    assert ranged_reply.in_reply_to == ranged.id
    assert ranged_reply.change_id == "chg-s"
    assert ranged_reply.file == "src/foo.py"
    assert ranged_reply.state is CommentState.ACTIVE
    assert ranged_reply.drifted is False
    assert ranged_reply.range == LineRange(side=Side.NEW, start=3, end=3)
    assert ranged_reply.anchor_snapshot == ["added"]

    lost_reply = reopen_reply(lost, change, text="please revisit", author="alice")
    assert lost_reply.drifted is True
    assert lost_reply.range is None
    assert lost_reply.anchor_snapshot == []

    file_level_reply = reopen_reply(
        file_level, change, text="please revisit", author="alice"
    )
    assert file_level_reply.drifted is False
    assert file_level_reply.range is None
    assert file_level_reply.anchor_snapshot == []

    assert ranged.state is CommentState.RESOLVED
    assert lost.state is CommentState.RESOLVED
    assert file_level.state is CommentState.RESOLVED


def test_reanchor_thread_moves_all_members_to_one_anchor() -> None:
    v1 = _v1()
    v2 = Version(
        revision="rev-2",
        files=[
            FileDiff(
                path="src/foo.py",
                hunks=[
                    Hunk(
                        old_start=10,
                        old_count=2,
                        new_start=10,
                        new_count=3,
                        lines=[
                            Line(kind="ctx", old_no=10, new_no=10, text="ctx1"),
                            Line(kind="add", old_no=None, new_no=11, text="added"),
                            Line(kind="ctx", old_no=11, new_no=12, text="ctx2"),
                        ],
                    )
                ],
            )
        ],
    )
    change = Change(id="chg-s", versions=[v1, v2])

    root = _comment(
        revision="rev-1",
        line_range=LineRange(side=Side.NEW, start=1, end=3),
        snapshot=["ctx1", "added", "ctx2"],
        state=CommentState.RESOLVED,
        id="c-root",
    )
    reply = _comment(
        revision="rev-1",
        line_range=LineRange(side=Side.NEW, start=1, end=3),
        state=CommentState.RESOLVED,
        id="c-reply",
    ).model_copy(update={"in_reply_to": "c-root"})
    tip = _comment(
        revision="rev-2",
        line_range=LineRange(side=Side.NEW, start=10, end=12),
        state=CommentState.ACTIVE,
        id="c-tip",
    ).model_copy(update={"in_reply_to": "c-reply"})

    updates = reanchor_thread(root, change, [root, reply, tip])
    updated = {comment.id: comment for comment in updates}

    anchor = LineRange(side=Side.NEW, start=10, end=12)
    assert updated["c-root"].range == anchor
    assert updated["c-reply"].range == anchor
    assert "c-tip" not in updated  # already at the anchor
    # the originals are untouched (updates are copies)
    assert root.range == LineRange(side=Side.NEW, start=1, end=3)
    assert reply.range == LineRange(side=Side.NEW, start=1, end=3)
