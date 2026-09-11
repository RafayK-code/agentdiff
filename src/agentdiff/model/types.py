from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class Side(str, Enum):
    OLD = "OLD"
    NEW = "NEW"


class CommentState(str, Enum):
    ACTIVE = "ACTIVE"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class LineRange(BaseModel):
    side: Side = Field(strict=True)
    start: int
    end: int

    @model_validator(mode="after")
    def _valid_span(self) -> LineRange:
        if self.start < 1:
            raise ValueError(f"start must be >= 1, got {self.start}")
        if self.end < self.start:
            raise ValueError(f"end {self.end} < start {self.start}")
        return self


class Comment(BaseModel):
    id: str
    change_id: str
    file: str
    range: LineRange | None = None
    text: str
    author: str
    thread_id: str | None = None
    state: CommentState = Field(strict=True)
    drifted: bool = False
    created_at: datetime
    updated_at: datetime
    anchor_snapshot: list[str] = Field(default_factory=list)


def new_comment_id() -> str:
    """Opaque, unique, non-deterministic comment id (uuid-based). (R5)"""
    return f"c-{uuid.uuid4().hex}"


class Line(BaseModel):
    kind: Literal["ctx", "add", "del"]
    old_no: int | None
    new_no: int | None
    text: str

    @field_validator("text")
    @classmethod
    def _no_newline(cls, v: str) -> str:
        if "\n" in v:
            raise ValueError("line text must not contain a newline")
        return v

    @model_validator(mode="after")
    def _check_numbering(self) -> Line:
        expected = {
            "add": (False, True),
            "del": (True, False),
            "ctx": (True, True),
        }
        has_old = self.old_no is not None
        has_new = self.new_no is not None
        if (has_old, has_new) != expected[self.kind]:
            raise ValueError(f"{self.kind} line has invalid numbering: {self!r}")
        return self


class Hunk(BaseModel):
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[Line] = Field(default_factory=list)

    @field_validator("old_start", "old_count", "new_start", "new_count")
    @classmethod
    def _non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"negative hunk number: {v}")
        return v

    @model_validator(mode="after")
    def _check_counts(self) -> Hunk:
        ctx = sum(1 for line in self.lines if line.kind == "ctx")
        add = sum(1 for line in self.lines if line.kind == "add")
        dele = sum(1 for line in self.lines if line.kind == "del")
        if ctx + dele != self.old_count:
            raise ValueError(f"old_count {self.old_count} != ctx+del {ctx + dele}")
        if ctx + add != self.new_count:
            raise ValueError(f"new_count {self.new_count} != ctx+add {ctx + add}")
        old_nos = [line.old_no for line in self.lines if line.old_no is not None]
        new_nos = [line.new_no for line in self.lines if line.new_no is not None]
        if any(b <= a for a, b in zip(old_nos, old_nos[1:], strict=False)):
            raise ValueError("old line numbers are not strictly increasing")
        if any(b <= a for a, b in zip(new_nos, new_nos[1:], strict=False)):
            raise ValueError("new line numbers are not strictly increasing")
        return self


class FileDiff(BaseModel):
    path: str
    old_path: str | None = None
    old_mode: str | None = None
    new_mode: str | None = None
    is_binary: bool = False
    hunks: list[Hunk] = Field(default_factory=list)


class Approval(BaseModel):
    status: Literal["APPROVED"]
    message: str | None
    author: str
    at: datetime


class Change(BaseModel):
    id: str
    prev_change: str | None = None
    branch: str | None = None
    base_revision: str | None = None
    head_revision: str | None = None
    approval: Approval | None = None
    files: list[FileDiff] = Field(default_factory=list)
    created_at: datetime | None = None
