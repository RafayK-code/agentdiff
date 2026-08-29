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
        self._mutate(change.id, lambda _old, comments: (change, comments))

    def load_change(self, change_id: str) -> Change | None:
        path = self._path_for(change_id)
        if not path.exists():
            return None
        return self._read_file(path)[0]

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
        file: str | None = None,
        state: CommentState | None = None,
        thread_id: str | None = None,
    ) -> list[Comment]:
        path = self._path_for(change_id)
        if not path.exists():
            return []
        comments = self._read_file(path)[1]
        result = []
        for comment in comments:
            if file is not None and comment.file != file:
                continue
            if state is not None and comment.state is not state:
                continue
            if thread_id is not None and not (
                comment.thread_id == thread_id or comment.id == thread_id
            ):
                continue
            result.append(comment)
        return result

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
        if comment.thread_id is not None and not any(
            c.thread_id == comment.thread_id or c.id == comment.thread_id
            for c in comments
        ):
            raise StoreError(f"unknown thread {comment.thread_id!r}")
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
        if comments[index].change_id != comment.change_id:
            raise StoreError(f"comment {comment.id!r} cannot move to another change")
        updated = comment.model_copy(update={"updated_at": self._now_utc()})
        new_comments = list(comments)
        new_comments[index] = updated
        return change, new_comments
