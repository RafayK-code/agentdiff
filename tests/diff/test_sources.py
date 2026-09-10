from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest
from tests.diff.conftest import load_fixture

from agentdiff.diff import NoCommitsError
from agentdiff.diff import sources as sources_module
from agentdiff.diff.parse import DiffParseError, parse_unified_diff
from agentdiff.diff.sources import (
    GitDiffError,
    diff_from_git,
    diff_from_patch,
)

BASIC = load_fixture("basic.patch")
NEW_FILE = load_fixture("new_file.patch")
RENAME = load_fixture("rename.patch")
DELETED = load_fixture("deleted_file.patch")
BINARY = load_fixture("binary.patch")

EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
HEAD_SHA = "aaaa0001"
PARENT_SHA = "bbbb0002"


class FakeGit:
    """Maps exact argv tuples to CompletedProcess results and records calls.

    Any argv not in the mapping raises, so unexpected commands fail the case.
    """

    def __init__(
        self, responses: dict[tuple[str, ...], subprocess.CompletedProcess[str]]
    ) -> None:
        self._responses = responses
        self.calls: list[list[str]] = []

    def __call__(self, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        key = tuple(args)
        self.calls.append(list(args))
        if key not in self._responses:
            raise AssertionError(f"unexpected git argv: {list(args)}")
        return self._responses[key]


def _result(
    argv: Sequence[str], *, returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=list(argv), returncode=returncode, stdout=stdout, stderr=stderr
    )


def _default_responses(
    diff_text: str,
) -> dict[tuple[str, ...], subprocess.CompletedProcess[str]]:
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
    }


def test_default_range_resolves_shas_and_parses_once(
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake = FakeGit(_default_responses(BASIC))

    change = diff_from_git(runner=fake)

    expected = parse_unified_diff(BASIC)
    assert change.base_revision == PARENT_SHA
    assert change.head_revision == HEAD_SHA
    assert change.files == expected.files
    assert change.id == expected.id
    assert fake.calls == [
        ["git", "rev-parse", "--verify", "--quiet", "HEAD^{commit}"],
        ["git", "rev-parse", "--verify", "--quiet", f"{HEAD_SHA}~1"],
        ["git", "diff", PARENT_SHA, HEAD_SHA],
    ]
    assert capsys.readouterr().err == ""


def test_explicit_base_and_head_resolve_to_shas() -> None:
    fake = FakeGit(
        {
            (
                "git",
                "rev-parse",
                "--verify",
                "--quiet",
                "feature-tip^{commit}",
            ): _result(
                ("git", "rev-parse", "--verify", "--quiet", "feature-tip^{commit}"),
                stdout=HEAD_SHA,
            ),
            ("git", "rev-parse", "--verify", "feature-base^{commit}"): _result(
                ("git", "rev-parse", "--verify", "feature-base^{commit}"),
                stdout="cccc0003",
            ),
            ("git", "diff", "cccc0003", HEAD_SHA): _result(
                ("git", "diff", "cccc0003", HEAD_SHA), stdout=BASIC
            ),
        }
    )

    change = diff_from_git(base="feature-base", head="feature-tip", runner=fake)

    assert change.base_revision == "cccc0003"
    assert change.head_revision == HEAD_SHA
    assert change.files == parse_unified_diff(BASIC).files
    assert fake.calls == [
        ["git", "rev-parse", "--verify", "--quiet", "feature-tip^{commit}"],
        ["git", "rev-parse", "--verify", "feature-base^{commit}"],
        ["git", "diff", "cccc0003", HEAD_SHA],
    ]


def test_head_only_defaults_base_to_parent() -> None:
    fake = FakeGit(
        {
            ("git", "rev-parse", "--verify", "--quiet", "topic^{commit}"): _result(
                ("git", "rev-parse", "--verify", "--quiet", "topic^{commit}"),
                stdout="dddd0004",
            ),
            ("git", "rev-parse", "--verify", "--quiet", "dddd0004~1"): _result(
                ("git", "rev-parse", "--verify", "--quiet", "dddd0004~1"),
                stdout="eeee0005",
            ),
            ("git", "diff", "eeee0005", "dddd0004"): _result(
                ("git", "diff", "eeee0005", "dddd0004"), stdout=BASIC
            ),
        }
    )

    change = diff_from_git(head="topic", runner=fake)

    assert change.base_revision == "eeee0005"
    assert change.head_revision == "dddd0004"
    assert fake.calls == [
        ["git", "rev-parse", "--verify", "--quiet", "topic^{commit}"],
        ["git", "rev-parse", "--verify", "--quiet", "dddd0004~1"],
        ["git", "diff", "eeee0005", "dddd0004"],
    ]


def test_base_only_defaults_head_to_head() -> None:
    fake = FakeGit(
        {
            ("git", "rev-parse", "--verify", "--quiet", "HEAD^{commit}"): _result(
                ("git", "rev-parse", "--verify", "--quiet", "HEAD^{commit}"),
                stdout="ffff0006",
            ),
            ("git", "rev-parse", "--verify", "main^{commit}"): _result(
                ("git", "rev-parse", "--verify", "main^{commit}"), stdout="0000aaaa"
            ),
            ("git", "diff", "0000aaaa", "ffff0006"): _result(
                ("git", "diff", "0000aaaa", "ffff0006"), stdout=BASIC
            ),
        }
    )

    change = diff_from_git(base="main", runner=fake)

    assert change.base_revision == "0000aaaa"
    assert change.head_revision == "ffff0006"
    assert fake.calls == [
        ["git", "rev-parse", "--verify", "--quiet", "HEAD^{commit}"],
        ["git", "rev-parse", "--verify", "main^{commit}"],
        ["git", "diff", "0000aaaa", "ffff0006"],
    ]


def test_root_commit_uses_empty_tree_as_base() -> None:
    fake = FakeGit(
        {
            ("git", "rev-parse", "--verify", "--quiet", "HEAD^{commit}"): _result(
                ("git", "rev-parse", "--verify", "--quiet", "HEAD^{commit}"),
                stdout=HEAD_SHA,
            ),
            ("git", "rev-parse", "--verify", "--quiet", f"{HEAD_SHA}~1"): _result(
                ("git", "rev-parse", "--verify", "--quiet", f"{HEAD_SHA}~1"),
                returncode=128,
                stderr="fatal: ambiguous argument",
            ),
            ("git", "hash-object", "-t", "tree", "/dev/null"): _result(
                ("git", "hash-object", "-t", "tree", "/dev/null"), stdout=EMPTY_TREE
            ),
            ("git", "diff", EMPTY_TREE, HEAD_SHA): _result(
                ("git", "diff", EMPTY_TREE, HEAD_SHA), stdout=NEW_FILE
            ),
        }
    )

    change = diff_from_git(runner=fake)

    assert change.base_revision == EMPTY_TREE
    assert change.head_revision == HEAD_SHA
    assert fake.calls == [
        ["git", "rev-parse", "--verify", "--quiet", "HEAD^{commit}"],
        ["git", "rev-parse", "--verify", "--quiet", f"{HEAD_SHA}~1"],
        ["git", "hash-object", "-t", "tree", "/dev/null"],
        ["git", "diff", EMPTY_TREE, HEAD_SHA],
    ]
    assert change.files == parse_unified_diff(NEW_FILE).files
    assert change.files[0].old_path is None


def test_unborn_head_raises_no_commits_error() -> None:
    fake = FakeGit(
        {
            ("git", "rev-parse", "--verify", "--quiet", "HEAD^{commit}"): _result(
                ("git", "rev-parse", "--verify", "--quiet", "HEAD^{commit}"),
                returncode=128,
                stderr="fatal: Needed a single revision",
            ),
        }
    )

    with pytest.raises(NoCommitsError) as excinfo:
        diff_from_git(runner=fake)

    assert isinstance(excinfo.value, GitDiffError)
    assert sources_module.NoCommitsError is NoCommitsError
    assert "no commits" in str(excinfo.value).lower()
    assert fake.calls == [["git", "rev-parse", "--verify", "--quiet", "HEAD^{commit}"]]


def test_explicit_bad_base_raises_git_error_without_fallback() -> None:
    fake = FakeGit(
        {
            ("git", "rev-parse", "--verify", "--quiet", "HEAD^{commit}"): _result(
                ("git", "rev-parse", "--verify", "--quiet", "HEAD^{commit}"),
                stdout=HEAD_SHA,
            ),
            ("git", "rev-parse", "--verify", "nope^{commit}"): _result(
                ("git", "rev-parse", "--verify", "nope^{commit}"),
                returncode=128,
                stderr="fatal: bad revision 'nope'",
            ),
        }
    )

    with pytest.raises(GitDiffError) as excinfo:
        diff_from_git(base="nope", head="HEAD", runner=fake)

    assert "bad revision" in excinfo.value.stderr
    assert excinfo.value.returncode == 128
    assert fake.calls == [
        ["git", "rev-parse", "--verify", "--quiet", "HEAD^{commit}"],
        ["git", "rev-parse", "--verify", "nope^{commit}"],
    ]


def test_same_range_yields_same_change_id() -> None:
    first = diff_from_git(runner=FakeGit(_default_responses(BASIC)))
    second = diff_from_git(runner=FakeGit(_default_responses(BASIC)))

    expected = parse_unified_diff(BASIC)
    assert first.id == second.id
    assert first.id == expected.id


def test_range_diff_text_parsed_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    real_parse = sources_module.parse_unified_diff

    def spy(text: str):
        calls.append(text)
        return real_parse(text)

    monkeypatch.setattr(sources_module, "parse_unified_diff", spy)

    diff_from_git(runner=FakeGit(_default_responses(BASIC)))

    assert calls == [BASIC]


def test_rename_delete_binary_canned_diff_parse() -> None:
    text = RENAME + DELETED + BINARY
    change = diff_from_git(runner=FakeGit(_default_responses(text)))

    assert len(change.files) == 3
    renamed = next(file for file in change.files if file.path == "new.py")
    assert renamed.old_path == "old.py"
    assert renamed.hunks == []
    deleted = next(file for file in change.files if file.path == "old.txt")
    assert deleted.old_mode == "100644"
    binary = next(file for file in change.files if file.path == "img.bin")
    assert binary.is_binary is True


def test_nonzero_git_diff_raises_git_error() -> None:
    responses = _default_responses("")
    responses[("git", "diff", PARENT_SHA, HEAD_SHA)] = _result(
        ("git", "diff", PARENT_SHA, HEAD_SHA),
        returncode=1,
        stderr="fatal: bad object",
    )
    fake = FakeGit(responses)

    with pytest.raises(GitDiffError) as excinfo:
        diff_from_git(runner=fake)

    assert excinfo.value.returncode == 1
    assert "bad object" in excinfo.value.stderr


def test_empty_range_diff_raises_parse_error() -> None:
    fake = FakeGit(_default_responses(""))

    with pytest.raises(DiffParseError):
        diff_from_git(runner=fake)


@pytest.mark.parametrize(
    "kind",
    ["valid", "missing", "non-diff"],
    ids=["valid-file", "missing-file", "non-diff-content"],
)
def test_diff_from_patch(kind: str, tmp_path: Path) -> None:
    if kind == "valid":
        patch = tmp_path / "change.patch"
        patch.write_text(BASIC, encoding="utf-8")
        change = diff_from_patch(patch)
        assert change.files == parse_unified_diff(BASIC).files
        assert change.base_revision is None
        assert change.head_revision is None
    elif kind == "missing":
        with pytest.raises(FileNotFoundError):
            diff_from_patch(tmp_path / "does-not-exist.patch")
    else:
        patch = tmp_path / "junk.patch"
        patch.write_text("this is not a diff\n", encoding="utf-8")
        with pytest.raises(DiffParseError):
            diff_from_patch(patch)
