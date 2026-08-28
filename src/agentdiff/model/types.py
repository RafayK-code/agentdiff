from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class Side(str, Enum):
    OLD = "OLD"
    NEW = "NEW"


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
        if self.kind == "add":
            if self.old_no is not None or self.new_no is None:
                raise ValueError(f"add line must have new_no only: {self!r}")
        elif self.kind == "del":
            if self.old_no is None or self.new_no is not None:
                raise ValueError(f"del line must have old_no only: {self!r}")
        else:
            if self.old_no is None or self.new_no is None:
                raise ValueError(f"ctx line must have both numbers: {self!r}")
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
    base_revision: str | None = None
    head_revision: str | None = None
    approval: Approval | None = None
    files: list[FileDiff] = Field(default_factory=list)
    created_at: datetime | None = None
