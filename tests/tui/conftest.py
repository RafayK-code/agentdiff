from __future__ import annotations

from datetime import datetime, timezone

from tests.diff.conftest import load_fixture

from agentdiff.diff.parse import parse_unified_diff
from agentdiff.model import (
    Change,
    Comment,
    CommentState,
    LineRange,
    Role,
    Side,
    Version,
)

NOW = datetime(2020, 1, 1, tzinfo=timezone.utc)

_MISSING = object()


def make_version(revision: str, *fixtures: str) -> Version:
    files = []
    for name in fixtures:
        files.extend(parse_unified_diff(load_fixture(name)).files)
    return Version(revision=revision, files=files)


def make_change(*versions: Version, id: str = "chg-s") -> Change:
    return Change(id=id, versions=list(versions))


def comment_factory(
    id: str,
    *,
    revision: str,
    file: str = "src/foo.py",
    range: LineRange | None = _MISSING,  # type: ignore[assignment]
    state: CommentState = CommentState.ACTIVE,
    text: str = "t",
    author: str = "alice",
    role: Role = Role.HUMAN,
    in_reply_to: str | None = None,
    anchor_snapshot: list[str] | None = None,
    change_id: str = "chg-s",
    drifted: bool = False,
    created_at: datetime = NOW,
    updated_at: datetime = NOW,
) -> Comment:
    if range is _MISSING:
        range = LineRange(side=Side.NEW, start=1, end=1)
    return Comment(
        id=id,
        change_id=change_id,
        revision=revision,
        file=file,
        range=range,
        text=text,
        author=author,
        role=role,
        state=state,
        drifted=drifted,
        in_reply_to=in_reply_to,
        anchor_snapshot=anchor_snapshot or [],
        created_at=created_at,
        updated_at=updated_at,
    )
