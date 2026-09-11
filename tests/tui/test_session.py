from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

from tests.diff.conftest import load_fixture

from agentdiff.diff import parse_unified_diff
from agentdiff.model import Change
from agentdiff.model.types import Side
from agentdiff.store import StoreError, create_store
from agentdiff.tui.session import load_shell_state
from agentdiff.tui.state import ShellStatus

BASIC = load_fixture("basic.patch")
DELETED = load_fixture("deleted_file.patch")
BINARY = load_fixture("binary.patch")
HEAD_SHA = "aaaa0001"
PARENT_SHA = "bbbb0002"


class FakeGit:
    """Maps exact argv tuples to CompletedProcess results.

    Any argv not in the mapping raises, so unexpected commands fail the case.
    ``raise_oserror`` simulates the git executable being unavailable.
    """

    def __init__(
        self,
        responses: dict[tuple[str, ...], subprocess.CompletedProcess[str]],
        *,
        raise_oserror: bool = False,
    ) -> None:
        self._responses = responses
        self._raise_oserror = raise_oserror
        self.calls: list[list[str]] = []

    def __call__(self, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        if self._raise_oserror:
            raise OSError("git not found")
        self.calls.append(list(args))
        key = tuple(args)
        if key not in self._responses:
            raise AssertionError(f"unexpected git argv: {list(args)}")
        return self._responses[key]


def _result(
    argv: Sequence[str], *, returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=list(argv), returncode=returncode, stdout=stdout, stderr=stderr
    )


def _success_responses(diff_text: str = BASIC) -> dict:
    return {
        ("git", "rev-parse", "--verify", "--quiet", "HEAD^{commit}"): _result(
            ("git", "rev-parse", "--verify", "--quiet", "HEAD^{commit}"),
            stdout=HEAD_SHA,
        ),
        ("git", "rev-parse", "--verify", "--quiet", f"{HEAD_SHA}~1"): _result(
            ("git", "rev-parse", "--verify", "--quiet", f"{HEAD_SHA}~1"),
            stdout=PARENT_SHA,
        ),
        ("git", "diff", PARENT_SHA, HEAD_SHA): _result(
            ("git", "diff", PARENT_SHA, HEAD_SHA), stdout=diff_text
        ),
        ("git", "symbolic-ref", "--short", "-q", "HEAD"): _result(
            ("git", "symbolic-ref", "--short", "-q", "HEAD"), stdout="main\n"
        ),
        ("git", "log", "-1", "--format=%s", "HEAD"): _result(
            ("git", "log", "-1", "--format=%s", "HEAD"), stdout="Add foo\n"
        ),
        ("git", "show", f"{HEAD_SHA}:src/foo.py"): _result(
            ("git", "show", f"{HEAD_SHA}:src/foo.py"),
            stdout="ctx1\nadded\nctx2\n",
        ),
    }


class _FailingStore:
    def save_change(self, change: Change) -> None:
        raise StoreError("disk full")


def test_load_shell_state_success_round_trips_through_store(tmp_path: Path) -> None:
    fake = FakeGit(_success_responses())

    state = load_shell_state(tmp_path, runner=fake)

    expected = parse_unified_diff(BASIC)
    assert state.status is ShellStatus.READY
    assert state.branch == "main"
    assert state.commit_title == "Add foo"
    assert state.change_id == expected.id
    assert state.base_revision == PARENT_SHA
    assert state.head_revision == HEAD_SHA
    assert len(state.files) == 1

    path = tmp_path / ".agentdiff" / f"{expected.id}.jsonl"
    assert path.exists()
    stored = create_store(tmp_path).load_change(expected.id)
    assert stored is not None
    assert stored.branch == "main"
    assert stored.base_revision == PARENT_SHA
    assert stored.head_revision == HEAD_SHA


def test_load_shell_state_unborn_head_is_error(tmp_path: Path) -> None:
    argv = ("git", "rev-parse", "--verify", "--quiet", "HEAD^{commit}")
    fake = FakeGit(
        {argv: _result(argv, returncode=128, stderr="fatal: Needed a single revision")}
    )

    state = load_shell_state(tmp_path, runner=fake)

    assert state.status is ShellStatus.ERROR
    assert "no commits" in (state.message or "").lower()


def test_load_shell_state_empty_diff_is_empty(tmp_path: Path) -> None:
    state = load_shell_state(tmp_path, runner=FakeGit(_success_responses("")))

    assert state.status is ShellStatus.EMPTY
    assert state.message == "Nothing to review."


def test_load_shell_state_nonzero_diff_is_git_error(tmp_path: Path) -> None:
    responses = _success_responses()
    responses[("git", "diff", PARENT_SHA, HEAD_SHA)] = _result(
        ("git", "diff", PARENT_SHA, HEAD_SHA),
        returncode=1,
        stderr="fatal: bad object",
    )

    state = load_shell_state(tmp_path, runner=FakeGit(responses))

    assert state.status is ShellStatus.ERROR
    assert (state.message or "").startswith("git error")


def test_load_shell_state_oserror_is_git_error(tmp_path: Path) -> None:
    state = load_shell_state(tmp_path, runner=FakeGit({}, raise_oserror=True))

    assert state.status is ShellStatus.ERROR
    assert (state.message or "").startswith("git error")


def test_load_shell_state_store_error_is_mapped(tmp_path: Path) -> None:
    state = load_shell_state(
        tmp_path, runner=FakeGit(_success_responses()), store=_FailingStore()
    )

    assert state.status is ShellStatus.ERROR
    assert (state.message or "").startswith("store error")
    assert "disk full" in (state.message or "")


def test_session_fetches_content_from_the_correct_revision_side(
    tmp_path: Path,
) -> None:
    responses = _success_responses(BASIC + DELETED + BINARY)
    responses[("git", "show", f"{PARENT_SHA}:old.txt")] = _result(
        ("git", "show", f"{PARENT_SHA}:old.txt"), stdout="line1\nline2\nline3\n"
    )
    fake = FakeGit(responses)

    state = load_shell_state(tmp_path, runner=fake)

    assert len(state.contents) == len(state.files)
    first = state.contents[0]
    assert first is not None and first.side is Side.NEW
    second = state.contents[1]
    assert second is not None and second.side is Side.OLD
    assert state.contents[2] is None
    assert [call for call in fake.calls if call[:2] == ["git", "show"]] == [
        ["git", "show", f"{HEAD_SHA}:src/foo.py"],
        ["git", "show", f"{PARENT_SHA}:old.txt"],
    ]
