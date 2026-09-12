from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from tests.tui.conftest import comment_factory, make_version

from agentdiff.export import export_json
from agentdiff.model import Change, CommentState

NOW = datetime(2020, 1, 1, tzinfo=timezone.utc)


def later(seconds: int) -> datetime:
    return NOW + timedelta(seconds=seconds)


def test_export_json_threads_array_derived_state() -> None:
    change = Change(id="chg-s", versions=[make_version("rev-1", "basic.patch")])
    root = comment_factory(
        "c-root", revision="rev-1", state=CommentState.ACTIVE, created_at=NOW
    )
    res = comment_factory(
        "c-res",
        revision="rev-1",
        in_reply_to="c-root",
        state=CommentState.RESOLVED,
        created_at=later(1),
    )
    other = comment_factory(
        "c-other", revision="rev-1", state=CommentState.ACTIVE, created_at=NOW
    )
    orphan = comment_factory(
        "c-orphan",
        revision="rev-1",
        in_reply_to="c-missing",
        state=CommentState.ACTIVE,
        created_at=NOW,
    )

    doc = json.loads(export_json(change, [root, res, other, orphan]))

    assert doc["schema_version"] == "1.0.0"
    assert doc["threads"] == [
        {"root": "c-root", "state": "resolved", "comments": ["c-root", "c-res"]},
        {"root": "c-other", "state": "open", "comments": ["c-other"]},
        {"root": "c-orphan", "state": "open", "comments": ["c-orphan"]},
    ]
    assert doc["comments"][0]["state"] == "ACTIVE"


def test_export_json_threads_respect_closed_filter() -> None:
    change = Change(id="chg-s", versions=[make_version("rev-1", "basic.patch")])
    croot = comment_factory(
        "c-croot", revision="rev-1", state=CommentState.ACTIVE, created_at=NOW
    )
    cclose = comment_factory(
        "c-cc",
        revision="rev-1",
        in_reply_to="c-croot",
        state=CommentState.CLOSED,
        created_at=later(1),
    )
    only_closed = comment_factory(
        "c-only", revision="rev-1", state=CommentState.CLOSED, created_at=NOW
    )

    default = json.loads(export_json(change, [croot, cclose, only_closed]))
    all_ = json.loads(
        export_json(change, [croot, cclose, only_closed], include_closed=True)
    )

    assert default["threads"] == [
        {"root": "c-croot", "state": "open", "comments": ["c-croot"]}
    ]
    assert all_["threads"] == [
        {"root": "c-croot", "state": "closed", "comments": ["c-croot", "c-cc"]},
        {"root": "c-only", "state": "closed", "comments": ["c-only"]},
    ]
