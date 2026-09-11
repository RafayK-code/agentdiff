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
    """Narrow persistence interface so backends are swappable (R10, D3).

    ``save_change`` is the ingest/append point: it merges incoming versions into
    the stored change (append-only, idempotent for a known ``revision``) and
    auto-``RESOLVED``s superseded non-closed comments (R4, R6). There is no
    version lock — older versions are read-only history.

    A comment's ``range`` is validated against its own ``revision``'s version;
    a reply (``in_reply_to`` set) must target the change's current version (R7,
    R8). ``list_comments`` filters by ``revision``/``file``/``state`` and hides
    ``CLOSED`` comments unless ``include_closed=True`` (R11).
    """

    def init(self) -> None: ...

    def save_change(self, change: Change) -> None: ...

    def load_change(self, change_id: str) -> Change | None: ...

    def list_changes(self, branch: str | None = None) -> list[Change]:
        """All stored changes, or one branch's when branch is given.
        ``branch=None`` means no filter (every change, across all branches).
        (R10)"""
        ...

    def add_comment(self, comment: Comment) -> None: ...

    def get_comment(self, comment_id: str) -> Comment: ...

    def update_comment(self, comment: Comment) -> None: ...

    def list_comments(
        self,
        change_id: str,
        *,
        revision: str | None = None,
        file: str | None = None,
        state: CommentState | None = None,
        include_closed: bool = False,
    ) -> list[Comment]: ...

    def close_comment(self, comment_id: str) -> Comment: ...
