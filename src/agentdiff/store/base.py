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
    """Narrow persistence interface so backends are swappable (R1, D3).

    Lock contract (R6a, §5.1): a change that is not its branch's tip is
    locked. ``add_comment`` and ``update_comment`` (which also covers replies
    and resolve/unresolve/close) raise ``StoreError`` when the target change is
    locked. Reads (``load_change``/``get_comment``/``list_comments``) are
    unaffected — a locked patchset stays readable.

    ``list_comments`` hides ``CLOSED`` comments unless ``include_closed=True``;
    ``include_closed`` is the sole gate (R5).
    """

    def init(self) -> None: ...

    def save_change(self, change: Change) -> None: ...

    def load_change(self, change_id: str) -> Change | None: ...

    def list_changes(self, branch: str | None = None) -> list[Change]:
        """All stored changes, or one branch's chain when branch is given.
        ``branch=None`` means no filter (every change, across all branches).
        (R3)"""
        ...

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
        include_closed: bool = False,
    ) -> list[Comment]: ...

    def close_comment(self, comment_id: str) -> Comment: ...
