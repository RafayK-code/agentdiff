from __future__ import annotations

import json

from agentdiff.model import Change


def test_change_chain_fields_roundtrip() -> None:
    change = Change(
        id="chg-01",
        prev_change="chg-00",
        branch="feat/x",
        base_revision="abc",
        head_revision="def",
    )
    raw = change.model_dump_json()
    loaded = Change.model_validate_json(raw)
    assert loaded == change
    assert loaded is not change
    assert json.loads(raw)["prev_change"] == "chg-00"
    assert json.loads(raw)["branch"] == "feat/x"


def test_change_chain_fields_default_to_none() -> None:
    bare = Change(id="chg-x", files=[])
    assert bare.prev_change is None
    assert bare.branch is None


def test_change_legacy_json_without_chain_fields_loads() -> None:
    change = Change(
        id="chg-01",
        prev_change="chg-00",
        branch="feat/x",
        base_revision="abc",
        head_revision="def",
    )
    raw = json.loads(change.model_dump_json())
    legacy = json.dumps(
        {k: v for k, v in raw.items() if k not in ("prev_change", "branch")}
    )
    loaded = Change.model_validate_json(legacy)
    assert loaded.prev_change is None
    assert loaded.branch is None
