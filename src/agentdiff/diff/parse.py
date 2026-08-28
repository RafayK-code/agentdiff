from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum

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


class _ParseState(Enum):
    SEEK = "SEEK"
    IN_FILE = "IN_FILE"
    HUNK = "HUNK"


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


@dataclass
class _Parser:
    """Line-by-line state machine over a diff text.

    state cycles SEEK -> IN_FILE -> HUNK as diff headers, file headers and
    hunk bodies are consumed; each handler reads exactly one line.
    """

    text: str
    files: list[FileDiff] = field(default_factory=list)
    cur: _FileBuilder | None = None
    hunk: _HunkBuilder | None = None
    old_no: int = 0
    new_no: int = 0
    old_left: int = 0
    new_left: int = 0
    prev_was_content: bool = False
    state: _ParseState = _ParseState.SEEK

    def _close_hunk(self, lineno: int) -> None:
        assert self.cur is not None
        assert self.hunk is not None
        self.cur.hunks.append(_close_hunk(self.hunk, lineno))
        self.hunk = None
        self.old_left = 0
        self.new_left = 0
        self.state = _ParseState.IN_FILE

    def _seek(self, line: str, lineno: int) -> None:
        # Outside any file section: skip blanks until the next diff header.
        if not line.strip():
            return
        if _DIFF_GIT_RE.match(line) is not None:
            parts = line.split()[2:]
            old_fb = parts[0] if parts else None
            new_fb = parts[1] if len(parts) > 1 else None
            self.cur = _FileBuilder(
                path=_normalize_path(new_fb) if new_fb is not None else None,
                old_path=_normalize_path(old_fb) if old_fb is not None else None,
            )
            self.state = _ParseState.IN_FILE
            return
        if _COMBINED_RE.match(line) is not None:
            raise DiffParseError("combined diffs are out of scope", lineno)
        old_m = _OLD_PATH_RE.match(line)
        if old_m is not None:
            self.cur = _FileBuilder(old_path=_normalize_path(old_m.group(1)))
            self.state = _ParseState.IN_FILE
            return
        if _GIT_BINARY_RE.match(line) is not None:
            raise DiffParseError("GIT binary patch payloads are out of scope", lineno)
        if line.startswith("@@"):
            raise DiffParseError("hunk header outside a file section", lineno)

    def _in_file(self, line: str, lineno: int) -> None:
        old_m = _OLD_PATH_RE.match(line)
        if old_m is not None:
            # A `---` header closes the previous file once it has hunks.
            if self.cur is not None and self.cur.hunks:
                self.files.append(_close_file(self.cur, lineno))
                self.cur = _FileBuilder(old_path=_normalize_path(old_m.group(1)))
            else:
                assert self.cur is not None
                self.cur.old_path = _normalize_path(old_m.group(1))
            self.prev_was_content = False
            return
        new_m = _NEW_PATH_RE.match(line)
        if new_m is not None:
            assert self.cur is not None
            path = _normalize_path(new_m.group(1))
            if path is not None:
                self.cur.path = path
            self.prev_was_content = False
            return
        assert self.cur is not None
        if _NO_NEWLINE_RE.match(line) is not None:
            if not self.prev_was_content:
                raise DiffParseError("no-newline marker outside a hunk body", lineno)
            self.prev_was_content = False
            return
        self.prev_was_content = False
        new_file_m = _NEW_FILE_MODE_RE.match(line)
        if new_file_m is not None:
            self.cur.new_mode = new_file_m.group(1)
            return
        deleted_file_m = _DELETED_FILE_MODE_RE.match(line)
        if deleted_file_m is not None:
            self.cur.old_mode = deleted_file_m.group(1)
            return
        old_mode_m = _OLD_MODE_RE.match(line)
        if old_mode_m is not None:
            self.cur.old_mode = old_mode_m.group(1)
            return
        new_mode_m = _NEW_MODE_RE.match(line)
        if new_mode_m is not None:
            self.cur.new_mode = new_mode_m.group(1)
            return
        rename_m = _RENAME_FROM_RE.match(line)
        if rename_m is not None:
            self.cur.old_path = rename_m.group(1)
            return
        rename_to_m = _RENAME_TO_RE.match(line)
        if rename_to_m is not None:
            self.cur.path = rename_to_m.group(1)
            return
        if _IGNORED_HEADER_RE.match(line) is not None:
            return
        if _BINARY_RE.match(line) is not None:
            self.cur.is_binary = True
            self.files.append(_close_file(self.cur, lineno))
            self.cur = None
            self.state = _ParseState.SEEK
            return
        if _GIT_BINARY_RE.match(line) is not None:
            raise DiffParseError("GIT binary patch payloads are out of scope", lineno)
        if _DIFF_GIT_RE.match(line) is not None:
            self.files.append(_close_file(self.cur, lineno))
            parts = line.split()[2:]
            old_fb = parts[0] if parts else None
            new_fb = parts[1] if len(parts) > 1 else None
            self.cur = _FileBuilder(
                path=_normalize_path(new_fb) if new_fb is not None else None,
                old_path=_normalize_path(old_fb) if old_fb is not None else None,
            )
            return
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
            if self.cur.path is None:
                raise DiffParseError("hunk header without a new path", lineno)
            self.hunk = _HunkBuilder(old_start, old_count, new_start, new_count)
            self.old_no = old_start
            self.new_no = new_start
            self.old_left = old_count
            self.new_left = new_count
            self.state = _ParseState.HUNK
            return
        raise DiffParseError(f"unexpected line in file section: {line!r}", lineno)

    def _hunk(self, line: str, lineno: int) -> None:
        if _NO_NEWLINE_RE.match(line) is not None:
            assert self.hunk is not None
            if not self.hunk.lines:
                raise DiffParseError(
                    "no-newline marker must follow a content line", lineno
                )
            return
        if line.startswith(" "):
            assert self.hunk is not None
            if self.old_left <= 0 or self.new_left <= 0:
                raise DiffParseError("context line exceeds hunk counts", lineno)
            self.hunk.lines.append(
                Line(
                    kind="ctx",
                    old_no=self.old_no,
                    new_no=self.new_no,
                    text=line[1:],
                )
            )
            self.prev_was_content = True
            self.old_left -= 1
            self.new_left -= 1
            self.old_no += 1
            self.new_no += 1
            if self.old_left == 0 and self.new_left == 0:
                self._close_hunk(lineno)
            return
        if line.startswith("-"):
            assert self.hunk is not None
            if self.old_left <= 0:
                raise DiffParseError("deleted line exceeds old count", lineno)
            self.hunk.lines.append(
                Line(kind="del", old_no=self.old_no, new_no=None, text=line[1:])
            )
            self.prev_was_content = True
            self.old_left -= 1
            self.old_no += 1
            if self.old_left == 0 and self.new_left == 0:
                self._close_hunk(lineno)
            return
        if line.startswith("+"):
            assert self.hunk is not None
            if self.new_left <= 0:
                raise DiffParseError("added line exceeds new count", lineno)
            self.hunk.lines.append(
                Line(kind="add", old_no=None, new_no=self.new_no, text=line[1:])
            )
            self.prev_was_content = True
            self.new_left -= 1
            self.new_no += 1
            if self.old_left == 0 and self.new_left == 0:
                self._close_hunk(lineno)
            return
        raise DiffParseError("unexpected line in hunk body", lineno)

    def parse(self) -> Change:
        lines = self.text.replace("\r\n", "\n").splitlines()
        for lineno, line in enumerate(lines):
            if self.state is _ParseState.SEEK:
                self._seek(line, lineno)
            elif self.state is _ParseState.IN_FILE:
                self._in_file(line, lineno)
            else:
                self._hunk(line, lineno)
        if self.state is _ParseState.HUNK:
            raise DiffParseError(
                "truncated hunk: header counts not satisfied", len(lines)
            )
        if self.state is _ParseState.IN_FILE:
            assert self.cur is not None
            self.files.append(_close_file(self.cur, len(lines)))
        if not self.files:
            raise DiffParseError("no diff file headers", 0)
        return Change(id=_derive_id(self.text), files=self.files)


def parse_unified_diff(text: str) -> Change:
    """Parse a full unified-diff changeset into a Change. Pure, I/O-free. (R1, R6)"""
    return _Parser(text).parse()
