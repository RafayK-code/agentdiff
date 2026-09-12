from __future__ import annotations

import os
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from agentdiff.model import (
    Change,
    Comment,
    CommentState,
    CommentValidationError,
    validate_comment,
)
from agentdiff.store.base import StoreError
from agentdiff.store.locking import file_lock


class JsonlStore:
    """JSONL-backed Store: one `.jsonl` file per change in `.agentdiff/` (R2)."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)
        self._dir = self._root / ".agentdiff"

    def init(self) -> None:
        self._ensure_dir()

    def save_change(self, change: Change) -> None:
        self._mutate(
            change.id,
            lambda old, comments: self._merge(old, comments, change),
        )

    def load_change(self, change_id: str) -> Change | None:
        path = self._path_for(change_id)
        if not path.exists():
            return None
        return self._read_file(path)[0]

    def list_changes(self, branch: str | None = None) -> list[Change]:
        """Every stored change, or one branch's chain when branch is given.

        ``branch=None`` means no filter. A missing ``.agentdiff/`` is an empty
        store; the read never creates the directory. Malformed records raise
        ``StoreError`` via ``_read_file`` (R3)."""
        result: list[Change] = []
        for path in sorted(self._dir.glob("*.jsonl")):
            result.append(self._read_file(path)[0])
        if branch is not None:
            result = [c for c in result if c.branch == branch]
        return result

    def add_comment(self, comment: Comment) -> None:
        self._mutate(
            comment.change_id,
            lambda change, comments: self._add(change, comments, comment),
        )

    def get_comment(self, comment_id: str) -> Comment:
        for path in sorted(self._dir.glob("*.jsonl")):
            for comment in self._read_file(path)[1]:
                if comment.id == comment_id:
                    return comment
        raise StoreError(f"unknown comment id {comment_id!r}")

    def update_comment(self, comment: Comment) -> None:
        self._mutate(
            comment.change_id,
            lambda change, comments: self._update(change, comments, comment),
        )

    def list_comments(
        self,
        change_id: str,
        *,
        revision: str | None = None,
        file: str | None = None,
        state: CommentState | None = None,
        include_closed: bool = False,
    ) -> list[Comment]:
        path = self._path_for(change_id)
        if not path.exists():
            return []
        comments = self._read_file(path)[1]
        result = []
        for comment in comments:
            if not include_closed and comment.state is CommentState.CLOSED:
                continue
            if revision is not None and comment.revision != revision:
                continue
            if file is not None and comment.file != file:
                continue
            if state is not None and comment.state is not state:
                continue
            result.append(comment)
        return result

    def close_comment(self, comment_id: str) -> Comment:
        comment = self.get_comment(comment_id)
        closed = comment.model_copy(update={"state": CommentState.CLOSED})
        self.update_comment(closed)
        return self.get_comment(comment_id)

    def _ensure_dir(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, change_id: str) -> Path:
        return self._dir / f"{change_id}.jsonl"

    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(timezone.utc)

    def _read_file(self, path: Path) -> tuple[Change, list[Comment]]:
        text = path.read_text(encoding="utf-8")
        if not text:
            raise StoreError("store file is empty")
        lines = text.split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        if not text.endswith("\n") and lines:
            lines.pop()
        if not lines:
            raise StoreError("store file has no change header")
        try:
            change = Change.model_validate_json(lines[0])
        except ValidationError as exc:
            raise StoreError("invalid change header", line=lines[0], lineno=1) from exc
        comments: list[Comment] = []
        for lineno, raw in enumerate(lines[1:], start=2):
            try:
                comments.append(Comment.model_validate_json(raw))
            except ValidationError as exc:
                raise StoreError("invalid JSONL line", line=raw, lineno=lineno) from exc
        return change, comments

    def _write_file(self, path: Path, change: Change, comments: list[Comment]) -> None:
        data = "\n".join(
            [change.model_dump_json()] + [c.model_dump_json() for c in comments]
        )
        data += "\n"
        tmp = path.with_name(f"{path.name}.tmp")
        tmp.write_text(data, encoding="utf-8")
        os.replace(tmp, path)

    def _mutate(
        self,
        change_id: str,
        fn: Callable[[Change | None, list[Comment]], tuple[Change, list[Comment]]],
    ) -> None:
        self._ensure_dir()
        with file_lock(self._dir / f"{change_id}.lock"):
            path = self._path_for(change_id)
            if path.exists():
                change, comments = self._read_file(path)
            else:
                change, comments = None, []
            new_change, new_comments = fn(change, comments)
            self._write_file(path, new_change, new_comments)

    def _merge(
        self,
        old: Change | None,
        comments: list[Comment],
        incoming: Change,
    ) -> tuple[Change, list[Comment]]:
        """Append only versions whose revision is new; auto-resolve superseded
        non-closed comments. Re-ingesting a known revision is a no-op. (R4, R6)"""
        if old is None:
            return incoming, comments
        known = {version.revision for version in old.versions}
        appended = [v for v in incoming.versions if v.revision not in known]
        if not appended:
            return old, comments
        versions = [*old.versions, *appended]
        current_revision = versions[-1].revision
        now = self._now_utc()
        resolved = [
            c
            if c.state is not CommentState.ACTIVE or c.revision == current_revision
            else c.model_copy(
                update={"state": CommentState.RESOLVED, "updated_at": now}
            )
            for c in comments
        ]
        return old.model_copy(update={"versions": versions}), resolved

    def _add(
        self,
        change: Change | None,
        comments: list[Comment],
        comment: Comment,
    ) -> tuple[Change, list[Comment]]:
        if change is None:
            raise StoreError(f"unknown change {comment.change_id!r}")
        try:
            validate_comment(comment, change)
        except CommentValidationError as exc:
            raise StoreError(str(exc)) from exc
        if any(c.id == comment.id for c in comments):
            raise StoreError(f"duplicate comment id {comment.id!r}")
        if comment.in_reply_to is not None:
            if not any(c.id == comment.in_reply_to for c in comments):
                raise StoreError(f"unknown comment {comment.in_reply_to!r}")
            if comment.revision != change.head_revision:
                raise StoreError(
                    f"reply must target the current revision "
                    f"{change.head_revision!r}, not {comment.revision!r}"
                )
        return change, comments + [comment]

    def _update(
        self,
        change: Change | None,
        comments: list[Comment],
        comment: Comment,
    ) -> tuple[Change, list[Comment]]:
        if change is None:
            raise StoreError(f"unknown change {comment.change_id!r}")
        index = next((i for i, c in enumerate(comments) if c.id == comment.id), None)
        if index is None:
            raise StoreError(f"unknown comment id {comment.id!r}")
        stored = comments[index]
        if stored.change_id != comment.change_id:
            raise StoreError(f"comment {comment.id!r} cannot move to another change")
        updated = comment.model_copy(update={"updated_at": self._now_utc()})
        new_comments = list(comments)
        new_comments[index] = updated
        return change, new_comments
