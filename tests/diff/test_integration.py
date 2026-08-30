from __future__ import annotations

import subprocess
from pathlib import Path

from agentdiff.diff.sources import diff_from_git


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _init_repo(repo: Path) -> None:
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "T")
    _git(repo, "config", "user.email", "t@e.c")


def _write_lines(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_real_git_repo_diff_hunks(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)

    _write_lines(repo / "data.txt", [f"line{i}" for i in range(1, 11)])
    _git(repo, "add", "data.txt")
    _git(repo, "commit", "-qm", "base")
    base = _git(repo, "rev-parse", "HEAD")

    lines = [f"line{i}" for i in range(1, 11)]
    lines[2] = "line3-changed"
    del lines[6]
    _write_lines(repo / "data.txt", lines)
    (repo / "newfile.txt").write_text("n1\nn2\nn3\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "head")
    head = _git(repo, "rev-parse", "HEAD")

    change = diff_from_git(base=base, head=head, cwd=repo)
    assert change.base_revision == base
    assert change.head_revision == head
    assert len(change.files) == 2

    data = next(f for f in change.files if f.path == "data.txt")
    assert len(data.hunks) == 1
    hunk = data.hunks[0]
    assert hunk.old_start == 1
    assert hunk.old_count == 10
    assert hunk.new_start == 1
    assert hunk.new_count == 9
    assert [line.old_no for line in hunk.lines if line.kind == "del"] == [3, 7]
    assert [line.new_no for line in hunk.lines if line.kind == "add"] == [3]

    new_file = next(f for f in change.files if f.path == "newfile.txt")
    assert new_file.old_path is None
    assert new_file.new_mode == "100644"
    assert len(new_file.hunks) == 1
    nf_hunk = new_file.hunks[0]
    assert (
        nf_hunk.old_start,
        nf_hunk.old_count,
        nf_hunk.new_start,
        nf_hunk.new_count,
    ) == (0, 0, 1, 3)
    assert [line.new_no for line in nf_hunk.lines] == [1, 2, 3]
    assert all(line.kind == "add" for line in nf_hunk.lines)


def test_real_git_repo_worktree_diff(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)

    _write_lines(repo / "data.txt", [f"line{i}" for i in range(1, 11)])
    _git(repo, "add", "data.txt")
    _git(repo, "commit", "-qm", "base")

    with (repo / "data.txt").open("a", encoding="utf-8") as handle:
        handle.write("line11\n")

    change = diff_from_git(cwd=repo)
    assert change.base_revision is None
    assert change.head_revision is None
    assert len(change.files) == 1
    assert change.files[0].path == "data.txt"
