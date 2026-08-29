from __future__ import annotations

from typing import Protocol, runtime_checkable

from agentdiff.model.types import Change, Comment, CommentState


class StoreError(RuntimeError):
    """A store-level failure (R7).

    Carries the offending line (if any) and its 1-based line number; the
    message includes them so malformed-JSONL errors name the bad content.
    """

    def __init__(
        self,
        message: str,
        *,
        line: str | None = None,
        lineno: int | None = None,
    ) -> None:
        self.line = line
        self.lineno = lineno
        detail = []
        if lineno is not None:
            detail.append(f"line {lineno}")
        if line is not None:
            detail.append(f"content {line!r}")
        if detail:
            message = f"{message} ({', '.join(detail)})"
        super().__init__(message)


@runtime_checkable
class Store(Protocol):
    """Narrow persistence interface so backends are swappable (R1, D3)."""

    def init(self) -> None: ...

    def save_change(self, change: Change) -> None: ...

    def load_change(self, change_id: str) -> Change | None: ...

    def add_comment(self, comment: Comment) -> None: ...

    def get_comment(self, comment_id: str) -> Comment: ...

    def update_comment(self, comment: Comment) -> None: ...

    def list_comments(
        self,
        change_id: str,
        *,
        file: str | None = None,
        state: CommentState | None = None,
        thread_id: str | None = None,
    ) -> list[Comment]: ...
