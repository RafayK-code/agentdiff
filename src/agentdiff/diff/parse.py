from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

import pydantic

from agentdiff.model.types import Change, FileDiff, Hunk, Line

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_DIFF_GIT_RE = re.compile(r"^diff --git ")
_COMBINED_RE = re.compile(r"^diff --(?:cc|combined) ")
_OLD_PATH_RE = re.compile(r"^---\s+(\S.*)$")
_NEW_PATH_RE = re.compile(r"^\+\+\+\s+(\S.*)$")
_BINARY_RE = re.compile(r"^Binary files .+ and .+ differ$")
_GIT_BINARY_RE = re.compile(r"^GIT binary patch$")
_NO_NEWLINE_RE = re.compile(r"^\\ No newline at end of file$")
_NEW_FILE_MODE_RE = re.compile(r"^new file mode (\d+)$")
_DELETED_FILE_MODE_RE = re.compile(r"^deleted file mode (\d+)$")
_OLD_MODE_RE = re.compile(r"^old mode (\d+)$")
_NEW_MODE_RE = re.compile(r"^new mode (\d+)$")
_RENAME_FROM_RE = re.compile(r"^(?:rename|copy) from (.+)$")
_RENAME_TO_RE = re.compile(r"^(?:rename|copy) to (.+)$")
_IGNORED_HEADER_RE = re.compile(r"^(?:index|similarity index|dissimilarity index) ")


class DiffParseError(ValueError):
    """Input is not a well-formed unified diff. (R6)

    Carries the 0-based input line where the error was detected, when known.
    """

    def __init__(self, message: str, line: int | None = None) -> None:
        self.line = line
        detail = f" at line {line}" if line is not None else ""
        super().__init__(f"{message}{detail}")


def _derive_id(text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"chg-{digest[:16]}"


def _normalize_path(path: str) -> str | None:
    if path == "/dev/null":
        return None
    if path.startswith(("a/", "b/")):
        return path[2:]
    return path


@dataclass
class _HunkBuilder:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[Line] = field(default_factory=list)


@dataclass
class _FileBuilder:
    path: str | None = None
    old_path: str | None = None
    old_mode: str | None = None
    new_mode: str | None = None
    is_binary: bool = False
    hunks: list[Hunk] = field(default_factory=list)


def _close_hunk(hunk: _HunkBuilder, lineno: int) -> Hunk:
    try:
        return Hunk(
            old_start=hunk.old_start,
            old_count=hunk.old_count,
            new_start=hunk.new_start,
            new_count=hunk.new_count,
            lines=hunk.lines,
        )
    except pydantic.ValidationError as exc:
        raise DiffParseError(f"invalid hunk model: {exc}", lineno) from exc


def _close_file(cur: _FileBuilder, lineno: int) -> FileDiff:
    if cur.old_path is not None and cur.old_path == cur.path:
        cur.old_path = None
    if cur.path is None:
        raise DiffParseError("file section has no new path", lineno)
    has_content = (
        bool(cur.hunks)
        or cur.is_binary
        or cur.old_mode is not None
        or cur.new_mode is not None
        or (cur.old_path is not None and cur.old_path != cur.path)
    )
    if not has_content:
        raise DiffParseError("file section with no hunks or metadata", lineno)
    try:
        return FileDiff(
            path=cur.path,
            old_path=cur.old_path,
            old_mode=cur.old_mode,
            new_mode=cur.new_mode,
            is_binary=cur.is_binary,
            hunks=cur.hunks,
        )
    except pydantic.ValidationError as exc:
        raise DiffParseError(f"invalid model: {exc}", lineno) from exc


def parse_unified_diff(text: str) -> Change:
    """Parse a full unified-diff changeset into a Change. Pure, I/O-free. (R1, R6)"""
    lines = text.replace("\r\n", "\n").splitlines()
    files: list[FileDiff] = []
    cur: _FileBuilder | None = None
    hunk: _HunkBuilder | None = None
    old_no = 0
    new_no = 0
    old_left = 0
    new_left = 0
    prev_was_content = False
    state = "SEEK"

    def close_hunk() -> None:
        nonlocal hunk, old_left, new_left, state
        assert cur is not None
        assert hunk is not None
        cur.hunks.append(_close_hunk(hunk, lineno))
        hunk = None
        old_left = 0
        new_left = 0
        state = "IN_FILE"

    for lineno, line in enumerate(lines):
        if state == "SEEK":
            if not line.strip():
                continue
            if _DIFF_GIT_RE.match(line) is not None:
                parts = line.split()[2:]
                old_fb = parts[0] if parts else None
                new_fb = parts[1] if len(parts) > 1 else None
                cur = _FileBuilder(
                    path=_normalize_path(new_fb) if new_fb is not None else None,
                    old_path=_normalize_path(old_fb) if old_fb is not None else None,
                )
                state = "IN_FILE"
                continue
            if _COMBINED_RE.match(line) is not None:
                raise DiffParseError("combined diffs are out of scope", lineno)
            old_m = _OLD_PATH_RE.match(line)
            if old_m is not None:
                cur = _FileBuilder(old_path=_normalize_path(old_m.group(1)))
                state = "IN_FILE"
                continue
            if _GIT_BINARY_RE.match(line) is not None:
                raise DiffParseError(
                    "GIT binary patch payloads are out of scope", lineno
                )
            if line.startswith("@@"):
                raise DiffParseError("hunk header outside a file section", lineno)
            continue

        if state == "IN_FILE":
            old_m = _OLD_PATH_RE.match(line)
            if old_m is not None:
                if cur is not None and cur.hunks:
                    files.append(_close_file(cur, lineno))
                    cur = _FileBuilder(old_path=_normalize_path(old_m.group(1)))
                else:
                    assert cur is not None
                    cur.old_path = _normalize_path(old_m.group(1))
                prev_was_content = False
                continue
            new_m = _NEW_PATH_RE.match(line)
            if new_m is not None:
                assert cur is not None
                path = _normalize_path(new_m.group(1))
                if path is not None:
                    cur.path = path
                prev_was_content = False
                continue
            assert cur is not None
            if _NO_NEWLINE_RE.match(line) is not None:
                if not prev_was_content:
                    raise DiffParseError(
                        "no-newline marker outside a hunk body", lineno
                    )
                prev_was_content = False
                continue
            prev_was_content = False
            new_file_m = _NEW_FILE_MODE_RE.match(line)
            if new_file_m is not None:
                cur.new_mode = new_file_m.group(1)
                continue
            deleted_file_m = _DELETED_FILE_MODE_RE.match(line)
            if deleted_file_m is not None:
                cur.old_mode = deleted_file_m.group(1)
                continue
            old_mode_m = _OLD_MODE_RE.match(line)
            if old_mode_m is not None:
                cur.old_mode = old_mode_m.group(1)
                continue
            new_mode_m = _NEW_MODE_RE.match(line)
            if new_mode_m is not None:
                cur.new_mode = new_mode_m.group(1)
                continue
            rename_m = _RENAME_FROM_RE.match(line)
            if rename_m is not None:
                cur.old_path = rename_m.group(1)
                continue
            rename_to_m = _RENAME_TO_RE.match(line)
            if rename_to_m is not None:
                cur.path = rename_to_m.group(1)
                continue
            if _IGNORED_HEADER_RE.match(line) is not None:
                continue
            if _BINARY_RE.match(line) is not None:
                cur.is_binary = True
                files.append(_close_file(cur, lineno))
                cur = None
                state = "SEEK"
                continue
            if _GIT_BINARY_RE.match(line) is not None:
                raise DiffParseError(
                    "GIT binary patch payloads are out of scope", lineno
                )
            if _DIFF_GIT_RE.match(line) is not None:
                files.append(_close_file(cur, lineno))
                parts = line.split()[2:]
                old_fb = parts[0] if parts else None
                new_fb = parts[1] if len(parts) > 1 else None
                cur = _FileBuilder(
                    path=_normalize_path(new_fb) if new_fb is not None else None,
                    old_path=_normalize_path(old_fb) if old_fb is not None else None,
                )
                continue
            if _COMBINED_RE.match(line) is not None:
                raise DiffParseError("combined diffs are out of scope", lineno)
            if line.startswith("@@"):
                hunk_m = _HUNK_RE.match(line)
                if hunk_m is None:
                    raise DiffParseError("malformed hunk header", lineno)
                old_start = int(hunk_m.group(1))
                old_count = int(hunk_m.group(2) or "1")
                new_start = int(hunk_m.group(3))
                new_count = int(hunk_m.group(4) or "1")
                if cur.path is None:
                    raise DiffParseError("hunk header without a new path", lineno)
                hunk = _HunkBuilder(old_start, old_count, new_start, new_count)
                old_no = old_start
                new_no = new_start
                old_left = old_count
                new_left = new_count
                state = "HUNK"
                continue
            raise DiffParseError(f"unexpected line in file section: {line!r}", lineno)

        if state == "HUNK":
            if _NO_NEWLINE_RE.match(line) is not None:
                assert hunk is not None
                if not hunk.lines:
                    raise DiffParseError(
                        "no-newline marker must follow a content line", lineno
                    )
                continue
            if line.startswith(" "):
                assert hunk is not None
                if old_left <= 0 or new_left <= 0:
                    raise DiffParseError("context line exceeds hunk counts", lineno)
                hunk.lines.append(
                    Line(kind="ctx", old_no=old_no, new_no=new_no, text=line[1:])
                )
                prev_was_content = True
                old_left -= 1
                new_left -= 1
                old_no += 1
                new_no += 1
                if old_left == 0 and new_left == 0:
                    close_hunk()
                continue
            if line.startswith("-"):
                assert hunk is not None
                if old_left <= 0:
                    raise DiffParseError("deleted line exceeds old count", lineno)
                hunk.lines.append(
                    Line(kind="del", old_no=old_no, new_no=None, text=line[1:])
                )
                prev_was_content = True
                old_left -= 1
                old_no += 1
                if old_left == 0 and new_left == 0:
                    close_hunk()
                continue
            if line.startswith("+"):
                assert hunk is not None
                if new_left <= 0:
                    raise DiffParseError("added line exceeds new count", lineno)
                hunk.lines.append(
                    Line(kind="add", old_no=None, new_no=new_no, text=line[1:])
                )
                prev_was_content = True
                new_left -= 1
                new_no += 1
                if old_left == 0 and new_left == 0:
                    close_hunk()
                continue
            raise DiffParseError("unexpected line in hunk body", lineno)

    if state == "HUNK":
        raise DiffParseError("truncated hunk: header counts not satisfied", len(lines))
    if state == "IN_FILE":
        assert cur is not None
        files.append(_close_file(cur, len(lines)))
    if not files:
        raise DiffParseError("no diff file headers", 0)
    return Change(id=_derive_id(text), files=files)
