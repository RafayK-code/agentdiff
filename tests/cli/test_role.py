from __future__ import annotations

import pytest
from tests.store.conftest import CanonicalStore

from agentdiff.cli import main
from agentdiff.model import CommentState, Role


def test_add_authors_agent_by_default(
    capsys: pytest.CaptureFixture[str], canonical_store: CanonicalStore
) -> None:
    rc_default = main(
        [
            "add",
            "src/foo.py",
            "--change",
            "chg-bbb",
            "--lines",
            "1-1",
            "--message",
            "why?",
            "--root",
            str(canonical_store.root),
        ]
    )
    id_default = capsys.readouterr().out.strip()
    rc_human = main(
        [
            "add",
            "src/foo.py",
            "--change",
            "chg-bbb",
            "--lines",
            "2-2",
            "--message",
            "hm",
            "--role",
            "human",
            "--author",
            "reviewer",
            "--root",
            str(canonical_store.root),
        ]
    )
    id_human = capsys.readouterr().out.strip()

    assert rc_default == 0
    default = canonical_store.store.get_comment(id_default)
    assert default.role is Role.AGENT
    assert default.author == "agentdiff"
    assert rc_human == 0
    human = canonical_store.store.get_comment(id_human)
    assert human.role is Role.HUMAN
    assert human.author == "reviewer"


def test_resolve_and_reopen_author_agent_by_default(
    capsys: pytest.CaptureFixture[str], canonical_store: CanonicalStore
) -> None:
    rc_rd = main(["resolve", "c-3", "--root", str(canonical_store.root)])
    resolve_default = canonical_store.store.get_comment(capsys.readouterr().out.strip())
    rc_rh = main(
        ["resolve", "c-1", "--role", "human", "--root", str(canonical_store.root)]
    )
    resolve_human = canonical_store.store.get_comment(capsys.readouterr().out.strip())
    rc_od = main(
        [
            "reopen",
            "c-2",
            "--message",
            "more",
            "--root",
            str(canonical_store.root),
        ]
    )
    reopen_default = canonical_store.store.get_comment(capsys.readouterr().out.strip())
    rc_oh = main(
        [
            "reopen",
            "c-m",
            "--message",
            "more",
            "--role",
            "human",
            "--root",
            str(canonical_store.root),
        ]
    )
    reopen_human = canonical_store.store.get_comment(capsys.readouterr().out.strip())

    assert rc_rd == 0
    assert resolve_default.role is Role.AGENT
    assert resolve_default.state is CommentState.RESOLVED
    assert rc_rh == 0
    assert resolve_human.role is Role.HUMAN
    assert resolve_human.state is CommentState.RESOLVED
    assert rc_od == 0
    assert reopen_default.role is Role.AGENT
    assert reopen_default.state is CommentState.ACTIVE
    assert rc_oh == 0
    assert reopen_human.role is Role.HUMAN
    assert reopen_human.state is CommentState.ACTIVE
