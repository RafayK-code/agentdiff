from __future__ import annotations

from pathlib import Path

import pytest
from tests.diff.conftest import load_fixture
from tests.store.conftest import (
    CanonicalStore,
    comment_factory,
)

from agentdiff.diff.parse import parse_unified_diff
from agentdiff.model import Change, CommentState
from agentdiff.store import StoreError, create_store


def _basic(change_id: str, **update: object) -> Change:
    change = parse_unified_diff(load_fixture("basic.patch"))
    return change.model_copy(update={"id": change_id, **update})


def test_list_changes_across_and_branch_filter(canonical_store: CanonicalStore) -> None:
    store = canonical_store.store
    all_changes = store.list_changes()
    assert {c.id for c in all_changes} == {"chg-aaa", "chg-bbb", "chg-mmm", "chg-ppp"}
    assert {c.branch for c in all_changes} == {"feat/x", "main", None}

    feat_x = store.list_changes(branch="feat/x")
    assert [c.id for c in feat_x] == ["chg-aaa", "chg-bbb"]
    assert all(c.branch == "feat/x" for c in feat_x)

    main = store.list_changes(branch="main")
    assert [c.id for c in main] == ["chg-mmm"]

    assert store.list_changes(branch="does-not-exist") == []
    assert store.list_changes(branch=None) == all_changes


def test_list_changes_empty_and_corrupt(tmp_path: Path) -> None:
    fresh = create_store(tmp_path)
    assert fresh.list_changes() == []
    assert fresh.list_changes(branch="main") == []
    assert (tmp_path / ".agentdiff").exists() is False

    corrupt_root = tmp_path / "corrupt"
    (corrupt_root / ".agentdiff").mkdir(parents=True)
    (corrupt_root / ".agentdiff" / "chg-bad.jsonl").write_text(
        "this is not json\n", encoding="utf-8"
    )
    store = create_store(corrupt_root)
    with pytest.raises(StoreError) as excinfo:
        store.list_changes()
    assert excinfo.value.lineno == 1
    assert excinfo.value.line == "this is not json"


def test_lock_lifecycle_writes_and_reads(tmp_path: Path) -> None:
    store = create_store(tmp_path)
    chg_aaa = _basic("chg-aaa", branch="feat/x")
    chg_bbb = _basic("chg-bbb", branch="feat/x", prev_change="chg-aaa")
    store.save_change(chg_aaa)
    store.add_comment(comment_factory(chg_aaa, id="c-1"))
    store.add_comment(comment_factory(chg_aaa, id="c-a"))

    store.save_change(chg_bbb)

    with pytest.raises(StoreError) as exc:
        store.add_comment(comment_factory(chg_aaa, id="c-x"))
    assert "locked" in str(exc.value)
    with pytest.raises(StoreError) as exc:
        store.update_comment(
            comment_factory(chg_aaa, id="c-1", state=CommentState.RESOLVED)
        )
    assert "locked" in str(exc.value)
    assert [c.id for c in store.list_comments("chg-aaa")] == ["c-1", "c-a"]

    store.add_comment(comment_factory(chg_bbb, id="c-tip"))
    store.update_comment(comment_factory(chg_bbb, id="c-tip"))

    assert store.load_change("chg-aaa") == chg_aaa
    assert store.get_comment("c-1").id == "c-1"


def test_save_change_chain_integrity(tmp_path: Path) -> None:
    store = create_store(tmp_path / "a")
    with pytest.raises(StoreError) as exc:
        store.save_change(_basic("chg-x", branch="feat/x", prev_change="chg-nope"))
    assert "chg-nope" in str(exc.value)

    store = create_store(tmp_path / "b")
    store.save_change(_basic("chg-aaa", branch="feat/x"))
    with pytest.raises(StoreError) as exc:
        store.save_change(_basic("chg-z", branch="main", prev_change="chg-aaa"))
    assert "chg-aaa" in str(exc.value)
    assert "main" in str(exc.value)

    store = create_store(tmp_path / "c")
    store.save_change(_basic("chg-aaa", branch="feat/x"))
    store.save_change(_basic("chg-bbb", branch="feat/x", prev_change="chg-aaa"))
    with pytest.raises(StoreError) as exc:
        store.save_change(_basic("chg-aaa", branch="feat/x", prev_change="chg-bbb"))
    assert "cycle" in str(exc.value)
