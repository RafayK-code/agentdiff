from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from shutil import rmtree

import pytest
from pydantic import ValidationError
from tests.diff.conftest import load_fixture
from tests.store.conftest import CanonicalStore, comment_factory

from agentdiff.diff.parse import parse_unified_diff
from agentdiff.model import (
    Change,
    CommentState,
    CommentValidationError,
    LineRange,
    Side,
)
from agentdiff.store import JsonlStore, Store, StoreBackend, StoreError, create_store
from agentdiff.store.locking import file_lock


def test_store_protocol_runtime_checkable(store: JsonlStore) -> None:
    class NoGetComment:
        def init(self) -> None: ...

        def save_change(self, change) -> None: ...

        def load_change(self, change_id: str) -> None: ...

        def add_comment(self, comment) -> None: ...

        def update_comment(self, comment) -> None: ...

        def list_comments(self, change_id: str, **kwargs) -> list: ...

    assert isinstance(store, Store) is True
    assert isinstance(NoGetComment(), Store) is False
    assert isinstance(object(), Store) is False


def test_missing_change_and_comment_semantics(
    store: JsonlStore, change: Change
) -> None:
    store.save_change(change)
    c_a = comment_factory(change, id="c-a")
    store.add_comment(c_a)
    change_b = parse_unified_diff(load_fixture("new_file.patch"))
    store.save_change(change_b)
    c_b = comment_factory(change_b, id="c-b", file="new.txt", range=None)
    store.add_comment(c_b)
    assert store.load_change("chg-nope") is None
    assert store.list_comments("chg-nope") == []
    with pytest.raises(StoreError):
        store.get_comment("c-ghost")
    assert store.get_comment("c-a") == c_a
    assert store.get_comment("c-b") == c_b


def test_a13_create_store_defaults_to_jsonl(tmp_path: Path, change: Change) -> None:
    store = create_store(tmp_path)
    assert isinstance(store, Store) is True
    store.save_change(change)
    assert store.load_change(change.id) == change
    assert (tmp_path / ".agentdiff" / f"{change.id}.jsonl").exists() is True


def test_a13_create_store_jsonl_backend_explicit(tmp_path: Path) -> None:
    store = create_store(tmp_path, backend=StoreBackend.JSONL)
    assert StoreBackend.JSONL.value == "jsonl"
    assert isinstance(store, Store) is True
    store.init()
    assert (tmp_path / ".agentdiff").exists() is True
    assert store.load_change("chg-x") is None


def test_a13_create_store_unknown_backend_raises(tmp_path: Path) -> None:
    with pytest.raises(StoreError) as excinfo:
        create_store(tmp_path, backend="sqlite")
    assert "sqlite" in str(excinfo.value)


def test_a13_create_store_accepts_str_root(tmp_path: Path, change: Change) -> None:
    store = create_store(str(tmp_path))
    assert isinstance(store, Store) is True
    store.save_change(change)
    assert store.load_change(change.id) == change
    assert (tmp_path / ".agentdiff" / f"{change.id}.jsonl").exists() is True


def test_change_and_comment_roundtrip(store: JsonlStore, change: Change) -> None:
    store.save_change(change)
    c1 = comment_factory(
        change,
        id="c-1",
        state=CommentState.ACTIVE,
        range=LineRange(side=Side.NEW, start=1, end=1),
    )
    c2 = comment_factory(change, id="c-2", range=None)
    store.add_comment(c1)
    store.add_comment(c2)
    loaded = store.load_change(change.id)
    comments = store.list_comments(change.id)
    assert loaded == change
    assert loaded is not change
    assert comments == [c1, c2]
    assert isinstance(comments[0].state, CommentState)
    assert comments[0].state is CommentState.ACTIVE
    assert comments[0].range.side is Side.NEW
    assert comments[1].range is None

    store.save_change(change)
    store.save_change(change.model_copy(update={"head_revision": "abc123"}))
    assert store.list_comments(change.id) == [c1, c2]
    assert store.load_change(change.id).head_revision == "abc123"


def test_store_dir_laziness(tmp_path: Path, change: Change) -> None:
    JsonlStore(tmp_path)
    assert (tmp_path / ".agentdiff").exists() is False

    store = JsonlStore(tmp_path)
    store.save_change(change)
    assert (tmp_path / ".agentdiff").exists()
    rmtree(tmp_path / ".agentdiff")
    with pytest.raises(StoreError):
        store.add_comment(comment_factory(change, id="c-1"))
    assert (tmp_path / ".agentdiff").exists()
    rmtree(tmp_path / ".agentdiff")
    with pytest.raises(StoreError):
        store.update_comment(
            comment_factory(change, id="c-1", state=CommentState.RESOLVED)
        )
    assert (tmp_path / ".agentdiff").exists()

    init_root = tmp_path / "init"
    init_store = JsonlStore(init_root)
    assert (init_root / ".agentdiff").exists() is False
    init_store.init()
    assert (init_root / ".agentdiff").exists() is True
    init_store.init()
    assert init_store.load_change(change.id) is None

    read_root = tmp_path / "read"
    reader = JsonlStore(read_root)
    assert reader.load_change("chg-x") is None
    assert reader.list_comments("chg-x") == []
    with pytest.raises(StoreError):
        reader.get_comment("c-x")
    assert (read_root / ".agentdiff").exists() is False


def test_add_valid_comments_accepted(store: JsonlStore, change: Change) -> None:
    store.save_change(change)
    c_line = comment_factory(
        change, id="c-ok", range=LineRange(side=Side.OLD, start=2, end=2)
    )
    c_file = comment_factory(change, id="c-file", range=None)
    assert store.add_comment(c_line) is None
    assert store.add_comment(c_file) is None
    assert store.get_comment("c-ok") == c_line
    assert store.get_comment("c-file").range is None


@pytest.mark.parametrize(
    "scenario",
    [
        "unknown-change",
        "invalid-file",
        "invalid-line-range",
        "nonexistent-thread",
        "duplicate-id",
        "typed-storeerror",
    ],
)
def test_add_comment_rejects_invalid(
    scenario: str, tmp_path: Path, store: JsonlStore, change: Change
) -> None:
    if scenario == "unknown-change":
        fresh = JsonlStore(tmp_path)
        c = comment_factory(change, id="c-x")
        with pytest.raises(StoreError):
            fresh.add_comment(c)
        assert fresh.list_comments(change.id) == []
        with pytest.raises(StoreError):
            fresh.get_comment("c-x")
    elif scenario == "invalid-file":
        store.save_change(change)
        c = comment_factory(change, id="c-bad", file="nope.py")
        with pytest.raises(StoreError):
            store.add_comment(c)
        assert store.list_comments(change.id) == []
    elif scenario == "invalid-line-range":
        store.save_change(change)
        c1 = comment_factory(
            change, id="c-oob", range=LineRange(side=Side.NEW, start=3, end=4)
        )
        with pytest.raises(StoreError):
            store.add_comment(c1)
        assert store.list_comments(change.id) == []
        change_m = parse_unified_diff(load_fixture("multiple_hunks.patch"))
        store.save_change(change_m)
        c2 = comment_factory(
            change_m,
            id="c-hi",
            file="m.txt",
            range=LineRange(side=Side.NEW, start=26, end=26),
        )
        with pytest.raises(StoreError):
            store.add_comment(c2)
        assert store.list_comments(change_m.id) == []
    elif scenario == "nonexistent-thread":
        store.save_change(change)
        c_root = comment_factory(change, id="c-root")
        store.add_comment(c_root)
        reply = comment_factory(change, id="c-ghost", thread_id="th-999")
        with pytest.raises(StoreError):
            store.add_comment(reply)
        assert store.list_comments(change.id) == [c_root]
    elif scenario == "duplicate-id":
        store.save_change(change)
        store.add_comment(comment_factory(change, id="c-dup"))
        c2 = comment_factory(change, id="c-dup", text="different")
        with pytest.raises(StoreError):
            store.add_comment(c2)
        assert [c.id for c in store.list_comments(change.id)] == ["c-dup"]
    else:
        store.save_change(change)
        cases = []
        with pytest.raises(StoreError) as excinfo:
            store.add_comment(comment_factory(change, id="c-bad", file="nope.py"))
        cases.append(excinfo.value)
        with pytest.raises(StoreError) as excinfo:
            store.add_comment(
                comment_factory(
                    change,
                    id="c-oob",
                    range=LineRange(side=Side.NEW, start=3, end=4),
                )
            )
        cases.append(excinfo.value)
        fresh = JsonlStore(tmp_path / "fresh")
        with pytest.raises(StoreError) as excinfo:
            fresh.add_comment(comment_factory(change, id="c-x"))
        cases.append(excinfo.value)
        for exc in cases:
            assert isinstance(exc, StoreError)
            assert not isinstance(exc, CommentValidationError)
            assert not isinstance(exc, ValidationError)
        assert "nope.py" in str(cases[0])
        assert "src/foo.py" in str(cases[1])
        assert any(ch.isdigit() for ch in str(cases[1]))


def test_update_semantics(tmp_path: Path, change: Change) -> None:
    store = create_store(tmp_path / "resolve")
    old = datetime(2000, 1, 1, 12, 0, tzinfo=timezone.utc)
    store.save_change(change)
    c1 = comment_factory(
        change,
        id="c-1",
        state=CommentState.ACTIVE,
        updated_at=old,
        created_at=datetime(2000, 1, 1, 11, 0, tzinfo=timezone.utc),
    )
    c2 = comment_factory(change, id="c-2")
    store.add_comment(c1)
    store.add_comment(c2)
    store.update_comment(
        comment_factory(
            change,
            id="c-1",
            state=CommentState.RESOLVED,
            updated_at=old,
            created_at=c1.created_at,
        )
    )
    resolved = store.get_comment("c-1")
    assert resolved.state is CommentState.RESOLVED
    assert resolved.updated_at > old
    assert resolved.created_at == c1.created_at
    assert store.list_comments(change.id) == [resolved, c2]

    store = create_store(tmp_path / "unknown")
    store.save_change(change)
    c1 = comment_factory(change, id="c-1")
    store.add_comment(c1)
    with pytest.raises(StoreError):
        store.update_comment(comment_factory(change, id="c-nope"))
    assert store.list_comments(change.id) == [c1]
    fresh = JsonlStore(tmp_path / "fresh")
    with pytest.raises(StoreError):
        fresh.update_comment(comment_factory(change, id="c-1"))

    store = create_store(tmp_path / "immutable")
    store.save_change(change)
    store.add_comment(comment_factory(change, id="c-1"))
    change_b = parse_unified_diff(load_fixture("new_file.patch"))
    store.save_change(change_b)
    tampered = comment_factory(change, id="c-1", change_id=change_b.id)
    with pytest.raises(StoreError):
        store.update_comment(tampered)
    assert store.get_comment("c-1").change_id == change.id

    store = create_store(tmp_path / "drifted")
    store.save_change(change)
    c1 = comment_factory(
        change,
        id="c-1",
        state=CommentState.ACTIVE,
        range=LineRange(side=Side.NEW, start=1, end=1),
        created_at=old,
        updated_at=old,
    )
    store.add_comment(c1)
    store.update_comment(
        comment_factory(
            change,
            id="c-1",
            state=CommentState.RESOLVED,
            range=LineRange(side=Side.NEW, start=1, end=1),
            created_at=old,
            updated_at=old,
        )
    )
    resolved = store.get_comment("c-1")
    assert resolved.state is CommentState.RESOLVED
    assert resolved.updated_at > old
    store.update_comment(
        comment_factory(
            change,
            id="c-1",
            state=CommentState.ACTIVE,
            range=LineRange(side=Side.NEW, start=1, end=1),
            created_at=old,
            updated_at=old,
        )
    )
    reopened = store.get_comment("c-1")
    assert reopened.state is CommentState.ACTIVE
    assert reopened.updated_at > resolved.updated_at
    store.update_comment(
        comment_factory(
            change,
            id="c-1",
            state=CommentState.ACTIVE,
            drifted=True,
            range=LineRange(side=Side.NEW, start=99, end=99),
            created_at=old,
            updated_at=old,
        )
    )
    drifted = store.get_comment("c-1")
    assert drifted.state is CommentState.ACTIVE
    assert drifted.drifted is True
    assert drifted.updated_at > reopened.updated_at
    assert drifted.range == LineRange(side=Side.NEW, start=99, end=99)


def test_list_comments_filters(tmp_path: Path, change: Change) -> None:
    store = create_store(tmp_path / "threads")
    store.save_change(change)
    root = comment_factory(change, id="c-root")
    r1 = comment_factory(change, id="c-r1", thread_id="c-root")
    r2 = comment_factory(change, id="c-r2", thread_id="c-root")
    store.add_comment(root)
    store.add_comment(r1)
    store.add_comment(r2)
    assert store.list_comments(change.id, thread_id="c-root") == [root, r1, r2]
    assert store.list_comments(change.id) == [root, r1, r2]

    store = create_store(tmp_path / "excludes")
    store.save_change(change)
    a_root = comment_factory(change, id="c-a")
    b_root = comment_factory(change, id="c-b")
    a_reply = comment_factory(change, id="c-ar", thread_id="c-a")
    b_reply = comment_factory(change, id="c-br", thread_id="c-b")
    store.add_comment(a_root)
    store.add_comment(b_root)
    store.add_comment(a_reply)
    store.add_comment(b_reply)
    assert store.list_comments(change.id, thread_id="c-a") == [a_root, a_reply]
    assert store.list_comments(change.id, thread_id="c-b") == [b_root, b_reply]
    assert store.list_comments(change.id) == [a_root, b_root, a_reply, b_reply]

    store = create_store(tmp_path / "files")
    store.save_change(change)
    c1 = comment_factory(change, id="c-1", file="src/foo.py")
    c2 = comment_factory(change, id="c-2", file="src/foo.py")
    store.add_comment(c1)
    store.add_comment(c2)
    change_b = parse_unified_diff(load_fixture("new_file.patch"))
    store.save_change(change_b)
    c3 = comment_factory(change_b, id="c-3", file="new.txt", range=None)
    store.add_comment(c3)
    assert store.list_comments(change.id, file="src/foo.py") == [c1, c2]
    assert store.list_comments(change.id, file="src/other.py") == []
    assert store.list_comments(change_b.id, file="new.txt") == [c3]

    store = create_store(tmp_path / "states")
    store.save_change(change)
    c_a = comment_factory(change, id="c-a", state=CommentState.ACTIVE)
    c_r = comment_factory(change, id="c-r", state=CommentState.RESOLVED)
    c_c = comment_factory(change, id="c-c", state=CommentState.CLOSED)
    store.add_comment(c_a)
    store.add_comment(c_r)
    store.add_comment(c_c)
    assert store.list_comments(change.id) == [c_a, c_r]
    assert store.list_comments(change.id, include_closed=True) == [c_a, c_r, c_c]
    assert store.list_comments(change.id, file="src/foo.py") == [c_a, c_r]
    assert store.list_comments(change.id, state=CommentState.ACTIVE) == [c_a]
    assert store.list_comments(change.id, state=CommentState.RESOLVED) == [c_r]
    assert store.list_comments(change.id, state=CommentState.CLOSED) == []
    assert store.list_comments(
        change.id, state=CommentState.CLOSED, include_closed=True
    ) == [c_c]
    assert store.list_comments(
        change.id, file="src/foo.py", state=CommentState.ACTIVE, thread_id=None
    ) == [c_a]
    assert (
        store.list_comments(
            change.id, file="src/other.py", state=CommentState.ACTIVE, thread_id=None
        )
        == []
    )
    assert (
        store.list_comments(
            change.id, file="src/foo.py", state=CommentState.CLOSED, thread_id=None
        )
        == []
    )
    assert (
        store.list_comments(
            change.id, file="src/foo.py", state=CommentState.ACTIVE, thread_id="nope"
        )
        == []
    )
    assert store.list_comments(change.id, file=None, state=None, thread_id=None) == [
        c_a,
        c_r,
    ]


def test_close_comment_sets_closed_retains_and_bumps(
    tmp_path: Path, change: Change
) -> None:
    store = create_store(tmp_path / "close")
    store.save_change(change)
    t0 = datetime(2000, 1, 1, 12, 0, tzinfo=timezone.utc)
    store.add_comment(comment_factory(change, id="c-1", created_at=t0, updated_at=t0))
    closed = store.close_comment("c-1")
    assert closed.id == "c-1"
    assert closed.state is CommentState.CLOSED
    assert store.get_comment("c-1").state is CommentState.CLOSED
    assert store.list_comments(change.id) == []
    assert store.list_comments(change.id, include_closed=True) == [closed]
    assert closed.updated_at > t0
    assert closed.created_at == t0


def test_close_comment_errors_and_lock_guard(
    tmp_path: Path, canonical_store: CanonicalStore
) -> None:
    fresh = create_store(tmp_path / "ghost")
    with pytest.raises(StoreError):
        fresh.close_comment("c-ghost")
    with pytest.raises(StoreError):
        canonical_store.store.close_comment("c-1")
    assert canonical_store.store.get_comment("c-1").state is CommentState.ACTIVE


def test_storeerror_carries_line_and_lineno(
    tmp_path: Path, store: JsonlStore, change: Change
) -> None:
    err = StoreError("boom", line="x", lineno=3)
    assert issubclass(StoreError, RuntimeError)
    assert err.line == "x"
    assert err.lineno == 3
    d = tmp_path / ".agentdiff"
    d.mkdir()
    (d / "chg-malformed.jsonl").write_text(
        change.model_dump_json() + "\n" + "this is not json\n", encoding="utf-8"
    )
    with pytest.raises(StoreError) as excinfo:
        store.list_comments("chg-malformed")
    assert excinfo.value.lineno == 2
    assert excinfo.value.line == "this is not json"
    assert "this is not json" in str(excinfo.value)


@pytest.mark.parametrize(
    "scenario",
    [
        "not-a-comment",
        "empty-file",
        "header-only",
        "unterminated-line",
        "unicode-separator",
    ],
    ids=[
        "valid-json-not-a-comment",
        "empty-file",
        "header-only",
        "unterminated-final-line",
        "literal-unicode-separator",
    ],
)
def test_store_format_tolerance(
    scenario: str, tmp_path: Path, store: JsonlStore, change: Change
) -> None:
    if scenario == "not-a-comment":
        d = tmp_path / ".agentdiff"
        d.mkdir()
        (d / "chg-model.jsonl").write_text(
            change.model_dump_json() + "\n" + '{"id": 123}\n', encoding="utf-8"
        )
        with pytest.raises(StoreError) as excinfo:
            store.list_comments("chg-model")
        assert excinfo.value.lineno == 2
    elif scenario == "empty-file":
        d = tmp_path / ".agentdiff"
        d.mkdir()
        (d / "chg-empty.jsonl").write_text("", encoding="utf-8")
        fresh = JsonlStore(tmp_path)
        with pytest.raises(StoreError):
            fresh.load_change("chg-empty")
    elif scenario == "header-only":
        store.save_change(change)
        assert store.load_change(change.id) == change
        assert store.list_comments(change.id) == []
    elif scenario == "unterminated-line":
        c1 = comment_factory(change, id="c-1")
        d = tmp_path / ".agentdiff"
        d.mkdir()
        (d / "chg-torn.jsonl").write_text(
            change.model_dump_json()
            + "\n"
            + c1.model_dump_json()
            + "\n"
            + '{"id":"c-torn"',
            encoding="utf-8",
        )
        assert store.list_comments("chg-torn") == [c1]
    else:
        c_u = comment_factory(change, id="c-u", text="a \u2028 b")
        d = tmp_path / ".agentdiff"
        d.mkdir()
        (d / "chg-u.jsonl").write_text(
            change.model_dump_json() + "\n" + c_u.model_dump_json() + "\n",
            encoding="utf-8",
        )
        comments = store.list_comments("chg-u")
        assert len(comments) == 1
        assert comments[0].text == "a \u2028 b"


def test_store_bridge_exports_required_members(tmp_path: Path) -> None:
    import agentdiff.store as s
    from agentdiff.store import (
        JsonlStore,
        Store,
        StoreBackend,
        StoreError,
        create_store,
    )

    assert {
        "Store",
        "StoreError",
        "JsonlStore",
        "StoreBackend",
        "create_store",
    } <= set(s.__all__)
    assert Store is s.Store
    assert StoreBackend is s.StoreBackend
    JsonlStore(tmp_path)
    assert isinstance(create_store(tmp_path), Store) is True
    try:
        raise StoreError("x")
    except StoreError:
        pass


def test_store_imports_no_ui_or_transport() -> None:
    import sys

    before = set(sys.modules)
    import agentdiff.store  # noqa: F401

    added = set(sys.modules) - before
    assert "textual" not in added
    assert "mcp" not in added
    assert "agentdiff.cli" not in added
    assert "agentdiff.mcp" not in added
    assert "agentdiff.tui" not in added


def _acquire_and_set(path: Path, done: threading.Event) -> None:
    with file_lock(path):
        done.set()


def test_file_lock_blocks_second_mutator(tmp_path: Path) -> None:
    path = tmp_path / "l.lock"
    done = threading.Event()
    outer = file_lock(path)
    outer.__enter__()
    try:
        t = threading.Thread(target=_acquire_and_set, args=(path, done))
        t.start()
        time.sleep(0.2)
        assert done.is_set() is False
    finally:
        outer.__exit__(None, None, None)
    assert done.wait(timeout=5) is True
    t.join()


def test_concurrent_adds_lose_nothing(tmp_path: Path, change: Change) -> None:
    store = JsonlStore(tmp_path)
    store.save_change(change)
    store_a = JsonlStore(tmp_path)
    store_b = JsonlStore(tmp_path)
    barrier = threading.Barrier(2)

    def writer(target: JsonlStore, prefix: str) -> None:
        barrier.wait()
        for i in range(50):
            target.add_comment(comment_factory(change, id=f"{prefix}-{i}"))

    ta = threading.Thread(target=writer, args=(store_a, "a"))
    tb = threading.Thread(target=writer, args=(store_b, "b"))
    ta.start()
    tb.start()
    ta.join()
    tb.join()
    comments = store.list_comments(change.id)
    assert len(comments) == 100
    ids = {c.id for c in comments}
    assert ids == {f"a-{i}" for i in range(50)} | {f"b-{i}" for i in range(50)}


def test_concurrent_distinct_changes(tmp_path: Path, change: Change) -> None:
    change_b = parse_unified_diff(load_fixture("new_file.patch"))
    store = JsonlStore(tmp_path)
    store.save_change(change)
    store.save_change(change_b)
    c_a = comment_factory(change, id="c-a")
    c_b = comment_factory(change_b, id="c-b", file="new.txt", range=None)
    barrier = threading.Barrier(2)

    def add_a() -> None:
        barrier.wait()
        store.add_comment(c_a)

    def add_b() -> None:
        barrier.wait()
        store.add_comment(c_b)

    ta = threading.Thread(target=add_a)
    tb = threading.Thread(target=add_b)
    ta.start()
    tb.start()
    ta.join()
    tb.join()
    assert store.get_comment("c-a") == c_a
    assert store.get_comment("c-b") == c_b


def test_lock_file_stable_across_rewrites(
    tmp_path: Path, store: JsonlStore, change: Change
) -> None:
    store.save_change(change)
    store.add_comment(comment_factory(change, id="c-1"))
    store.add_comment(comment_factory(change, id="c-2"))
    store.update_comment(comment_factory(change, id="c-1", state=CommentState.RESOLVED))
    assert (tmp_path / ".agentdiff" / f"{change.id}.lock").exists() is True
    assert [c.id for c in store.list_comments(change.id)] == ["c-1", "c-2"]
