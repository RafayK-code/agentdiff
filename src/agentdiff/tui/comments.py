from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum

from agentdiff.anchor import (
    RESOLVE_AUTHOR,
    ThreadState,
    group_threads,
    is_resolve_comment,
    is_resolved_thread,
    reopen_reply,
    resolution_reply,
    snapshot_lines,
    thread_members,
    thread_root,
    thread_root_id,
    thread_tip,
)
from agentdiff.model.types import (
    Change,
    Comment,
    CommentState,
    LineRange,
    Side,
    new_comment_id,
)
from agentdiff.store.base import Store, StoreError
from agentdiff.tui.render import DisplayLine, RenderedDiff, RowKind, line_index

DEFAULT_AUTHOR = "reviewer"
DRIFTED_NOTE = "location not found in patch"


class DraftKind(str, Enum):
    NEW = "new"
    REPLY = "reply"
    REOPEN = "reopen"


@dataclass(frozen=True)
class Selection:
    side: Side = Side.NEW
    anchor: int | None = None
    cursor: int | None = None


def select_line(selection: Selection, line: int | None) -> Selection:
    return replace(selection, anchor=line, cursor=line)


def extend_to(selection: Selection, line: int | None) -> Selection:
    if selection.anchor is None:
        return replace(selection, anchor=line, cursor=line)
    return replace(selection, cursor=line)


def selection_range(selection: Selection) -> LineRange | None:
    if selection.anchor is None or selection.cursor is None:
        return None
    return LineRange(
        side=selection.side,
        start=min(selection.anchor, selection.cursor),
        end=max(selection.anchor, selection.cursor),
    )


@dataclass(frozen=True)
class EditorDraft:
    file: str
    kind: DraftKind
    anchor: LineRange | None = None
    text: str = ""
    in_reply_to: str | None = None
    drifted: bool = False
    quoted: str | None = None
    editing_id: str | None = None


def new_draft(file: str, anchor: LineRange | None) -> EditorDraft:
    return EditorDraft(file=file, kind=DraftKind.NEW, anchor=anchor)


def reply_draft(parent: Comment) -> EditorDraft:
    return EditorDraft(
        file=parent.file,
        kind=DraftKind.REPLY,
        anchor=parent.range,
        in_reply_to=parent.id,
    )


def reopen_draft(
    comment: Comment,
    comments: Sequence[Comment],
    change: Change,
    *,
    author: str = DEFAULT_AUTHOR,
) -> EditorDraft:
    """Reopen the thread containing ``comment`` by replying at its tip. (R8)

    The draft re-anchors and quotes the thread **root** but attaches to the
    thread **tip**, so a linear chain never branches. (Feedback 4)
    """
    root = thread_root(comment, comments)
    tip = thread_tip(comment, comments)
    reply = reopen_reply(root, change, text="", author=author)
    return EditorDraft(
        file=root.file,
        kind=DraftKind.REOPEN,
        anchor=reply.range,
        in_reply_to=tip.id,
        drifted=reply.drifted,
        quoted=root.text,
    )


def set_draft_text(draft: EditorDraft, text: str) -> EditorDraft:
    return replace(draft, text=text)


def move_anchor(draft: EditorDraft, delta: int, valid: Sequence[int]) -> EditorDraft:
    if not valid:
        return draft
    side = draft.anchor.side if draft.anchor is not None else Side.NEW
    current = draft.anchor.start if draft.anchor is not None else None
    if delta > 0:
        larger = [line for line in valid if current is None or line > current]
        line = larger[0] if larger else (current if current is not None else valid[-1])
    elif delta < 0:
        smaller = [line for line in valid if current is None or line < current]
        line = (
            smaller[-1] if smaller else (current if current is not None else valid[0])
        )
    else:
        line = current if current is not None else valid[0]
    return replace(
        draft,
        anchor=LineRange(side=side, start=line, end=line),
        drifted=False,
    )


def draft_to_comment(
    draft: EditorDraft,
    change: Change,
    *,
    author: str = DEFAULT_AUTHOR,
    now: datetime | None = None,
) -> Comment:
    current = change.current
    if current is None:
        raise ValueError(f"change {change.id!r} has no version to comment on")
    timestamp = now if now is not None else datetime.now(timezone.utc)
    anchor_snapshot = (
        snapshot_lines(current, draft.file, draft.anchor)
        if draft.anchor is not None
        else []
    )
    return Comment(
        id=draft.editing_id or new_comment_id(),
        change_id=change.id,
        revision=current.revision,
        file=draft.file,
        range=draft.anchor,
        text=draft.text,
        author=author,
        in_reply_to=draft.in_reply_to,
        state=CommentState.ACTIVE,
        drifted=draft.drifted,
        created_at=timestamp,
        updated_at=timestamp,
        anchor_snapshot=anchor_snapshot,
    )


@dataclass(frozen=True)
class PendingBuffer:
    items: tuple[Comment, ...] = ()


@dataclass(frozen=True)
class FlushResult:
    written: tuple[Comment, ...]
    remaining: tuple[Comment, ...]
    error: str | None = None


def pending_count(buffer: PendingBuffer) -> int:
    return len(buffer.items)


def put_pending(buffer: PendingBuffer, comment: Comment) -> PendingBuffer:
    items = list(buffer.items)
    for index, existing in enumerate(items):
        if existing.id == comment.id:
            items[index] = comment
            return PendingBuffer(items=tuple(items))
    items.append(comment)
    return PendingBuffer(items=tuple(items))


def remove_pending(buffer: PendingBuffer, comment_id: str) -> PendingBuffer:
    items = tuple(comment for comment in buffer.items if comment.id != comment_id)
    if items == buffer.items:
        return buffer
    return PendingBuffer(items=items)


def flush_comments(buffer: PendingBuffer, store: Store) -> FlushResult:
    written: list[Comment] = []
    for index, comment in enumerate(buffer.items):
        try:
            store.add_comment(comment)
        except StoreError as exc:
            return FlushResult(
                written=tuple(written),
                remaining=tuple(buffer.items[index:]),
                error=str(exc),
            )
        written.append(comment)
    return FlushResult(written=tuple(written), remaining=())


@dataclass(frozen=True)
class ThreadedComment:
    comment: Comment
    replies: tuple[Comment, ...] = ()


@dataclass(frozen=True)
class CommentView:
    inline: tuple[ThreadedComment, ...]
    resolved: tuple[Comment, ...]
    hidden: tuple[Comment, ...]


def build_comment_view(comments: Sequence[Comment], change: Change) -> CommentView:
    head = change.head_revision
    inline_comments = [
        comment
        for comment in comments
        if comment.state is CommentState.ACTIVE and comment.revision == head
    ]
    inline_ids = {comment.id for comment in inline_comments}
    replies_by_parent: dict[str, list[Comment]] = {}
    roots: list[Comment] = []
    for comment in inline_comments:
        if comment.in_reply_to is not None and comment.in_reply_to in inline_ids:
            replies_by_parent.setdefault(comment.in_reply_to, []).append(comment)
        else:
            roots.append(comment)
    inline = tuple(
        ThreadedComment(
            comment=root,
            replies=tuple(replies_by_parent.get(root.id, ())),
        )
        for root in roots
    )
    resolved = tuple(
        comment for comment in comments if comment.state is CommentState.RESOLVED
    )
    hidden = tuple(
        comment for comment in comments if comment.state is CommentState.CLOSED
    )
    return CommentView(inline=inline, resolved=resolved, hidden=hidden)


def thread_rows(
    comment_rows: Mapping[int, Comment],
    comment: Comment,
    comments: Sequence[Comment],
) -> tuple[int, ...]:
    """The display lines of the whole chain containing ``comment``. (Feedback 4)"""
    members = {member.id for member in thread_members(comment, comments)}
    return tuple(
        sorted(index for index, row in comment_rows.items() if row.id in members)
    )


@dataclass(frozen=True)
class CommentAnnotation:
    comment: Comment
    depth: int = 0
    pending: bool = False
    note: str | None = None
    resolved: bool = False
    reply: bool = False


@dataclass(frozen=True)
class AnnotatedDiff:
    rendered: RenderedDiff
    comment_rows: dict[int, Comment]
    pending: frozenset[str]


def _note_for(comment: Comment) -> str | None:
    return DRIFTED_NOTE if comment.drifted else None


def _threaded(pool: Sequence[Comment]) -> list[Comment]:
    by_id = {comment.id: comment for comment in pool}
    children: dict[str, list[Comment]] = {}
    roots: list[Comment] = []
    for comment in pool:
        parent = comment.in_reply_to
        if parent is not None and parent in by_id:
            children.setdefault(parent, []).append(comment)
        else:
            roots.append(comment)
    ordered: list[Comment] = []

    def visit(comment: Comment) -> None:
        ordered.append(comment)
        for child in children.get(comment.id, ()):
            visit(child)

    for root in roots:
        visit(root)
    return ordered


def inline_annotations(
    view: CommentView, pending: PendingBuffer, file: str
) -> tuple[CommentAnnotation, ...]:
    pool: list[Comment] = []
    for thread in view.inline:
        if thread.comment.file == file:
            pool.append(thread.comment)
        pool.extend(reply for reply in thread.replies if reply.file == file)
    pool.extend(comment for comment in view.resolved if comment.file == file)
    pool.extend(comment for comment in pending.items if comment.file == file)
    if not pool:
        return ()
    by_id = {comment.id: comment for comment in pool}
    resolved_ids = {comment.id for comment in view.resolved}
    pending_ids = {comment.id for comment in pending.items}

    def depth_of(comment: Comment) -> int:
        depth = 0
        seen: set[str] = set()
        parent = comment.in_reply_to
        while parent is not None and parent in by_id and parent not in seen:
            seen.add(parent)
            depth += 1
            parent = by_id[parent].in_reply_to
        return depth

    annotations: list[CommentAnnotation] = []
    for comment in _threaded(pool):
        resolved = comment.id in resolved_ids
        annotations.append(
            CommentAnnotation(
                comment=comment,
                depth=depth_of(comment),
                pending=comment.id in pending_ids,
                resolved=resolved,
                reply=comment.in_reply_to is not None,
                note=_note_for(comment),
            )
        )
    return tuple(annotations)


def _anchor_index(rendered: RenderedDiff, comment: Comment) -> int:
    if comment.range is not None:
        index = line_index(rendered, comment.range.side)
        for number in (comment.range.end, comment.range.start):
            if number in index:
                return index[number]
    return 0


def _comment_line(annotation: CommentAnnotation) -> DisplayLine:
    indent = "  " * (annotation.depth + 1)
    connector = "\u21b3 " if annotation.reply else ""
    marker = "[pending] " if annotation.pending else ""
    note = f"  ({annotation.note})" if annotation.note else ""
    comment = annotation.comment
    return DisplayLine(
        kind=RowKind.COMMENT,
        text=f"{indent}{connector}{marker}{comment.author}: {comment.text}{note}",
    )


def annotate(
    rendered: RenderedDiff, annotations: Sequence[CommentAnnotation]
) -> AnnotatedDiff:
    if not annotations:
        return AnnotatedDiff(rendered=rendered, comment_rows={}, pending=frozenset())
    queues: dict[int, list[CommentAnnotation]] = {}
    for annotation in annotations:
        position = _anchor_index(rendered, annotation.comment)
        queues.setdefault(position, []).append(annotation)
    lines: list[DisplayLine] = []
    comment_rows: dict[int, Comment] = {}
    pending_ids: set[str] = set()
    for index, line in enumerate(rendered.lines):
        lines.append(line)
        for annotation in queues.get(index, ()):
            comment_rows[len(lines)] = annotation.comment
            if annotation.pending:
                pending_ids.add(annotation.comment.id)
            lines.append(_comment_line(annotation))
    insertions = sorted(queues)
    hunk_starts = tuple(
        start + sum(1 for position in insertions if position < start)
        for start in rendered.hunk_starts
    )
    return AnnotatedDiff(
        rendered=RenderedDiff(lines=tuple(lines), hunk_starts=hunk_starts),
        comment_rows=comment_rows,
        pending=frozenset(pending_ids),
    )


class CommentKind(str, Enum):
    ACTIVE = "active"
    PENDING = "pending"
    RESOLVED = "resolved"


@dataclass(frozen=True)
class AnchorBox:
    start: int
    end: int
    kind: CommentKind


_KIND_PRECEDENCE = {
    CommentKind.ACTIVE: 0,
    CommentKind.PENDING: 1,
    CommentKind.RESOLVED: 2,
}


def _annotation_kind(annotation: CommentAnnotation) -> CommentKind:
    if annotation.resolved:
        return CommentKind.RESOLVED
    if annotation.pending:
        return CommentKind.PENDING
    return CommentKind.ACTIVE


def anchor_boxes(
    rendered: RenderedDiff, annotations: Sequence[CommentAnnotation]
) -> tuple[AnchorBox, ...]:
    """Merged display-line spans for anchored comments. Pure. (Feedback 2)"""
    spans: list[list[int]] = []
    kinds: list[CommentKind] = []
    for annotation in annotations:
        line_range = annotation.comment.range
        if line_range is None:
            continue
        index = line_index(rendered, line_range.side)
        positions = [
            index[number]
            for number in (line_range.start, line_range.end)
            if number in index
        ]
        if not positions:
            continue
        spans.append([min(positions), max(positions)])
        kinds.append(_annotation_kind(annotation))
    if not spans:
        return ()
    ordered = sorted(
        zip(spans, kinds, strict=True), key=lambda item: (item[0][0], item[0][1])
    )
    merged: list[list[int]] = []
    merged_kinds: list[CommentKind] = []
    for (start, end), kind in ordered:
        if merged and start <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], end)
            if _KIND_PRECEDENCE[kind] > _KIND_PRECEDENCE[merged_kinds[-1]]:
                merged_kinds[-1] = kind
        else:
            merged.append([start, end])
            merged_kinds.append(kind)
    return tuple(
        AnchorBox(start=start, end=end, kind=kind)
        for (start, end), kind in zip(merged, merged_kinds, strict=True)
    )


@dataclass(frozen=True)
class FileCommentCounts:
    draft: int = 0
    resolved: int = 0
    unresolved: int = 0


def comment_counts(
    view: CommentView, pending: PendingBuffer
) -> dict[str, FileCommentCounts]:
    """Per-file draft / resolved / unresolved counts. Pure. (Feedback 3)

    ``draft`` counts pending comments; ``resolved`` / ``unresolved`` count
    conversations by their latest member. A conversation with a newer pending
    reply is a draft, not resolved.
    """
    pool: list[Comment] = []
    for thread in view.inline:
        pool.append(thread.comment)
        pool.extend(thread.replies)
    pool.extend(view.resolved)
    pool.extend(pending.items)
    pending_ids = {comment.id for comment in pending.items}

    draft: dict[str, int] = {}
    resolved: dict[str, int] = {}
    unresolved: dict[str, int] = {}
    for comment in pending.items:
        draft[comment.file] = draft.get(comment.file, 0) + 1
    for thread in group_threads(pool):
        latest = thread.members[-1]
        if latest.id in pending_ids:
            continue
        if thread.state is ThreadState.RESOLVED:
            resolved[latest.file] = resolved.get(latest.file, 0) + 1
        elif thread.state is ThreadState.OPEN:
            unresolved[latest.file] = unresolved.get(latest.file, 0) + 1

    files = set(draft) | set(resolved) | set(unresolved)
    return {
        file: FileCommentCounts(
            draft=draft.get(file, 0),
            resolved=resolved.get(file, 0),
            unresolved=unresolved.get(file, 0),
        )
        for file in files
    }


__all__ = [
    "DEFAULT_AUTHOR",
    "DRIFTED_NOTE",
    "RESOLVE_AUTHOR",
    "AnchorBox",
    "AnnotatedDiff",
    "CommentAnnotation",
    "CommentKind",
    "CommentView",
    "DraftKind",
    "EditorDraft",
    "FileCommentCounts",
    "FlushResult",
    "PendingBuffer",
    "Selection",
    "ThreadedComment",
    "anchor_boxes",
    "annotate",
    "build_comment_view",
    "comment_counts",
    "draft_to_comment",
    "extend_to",
    "flush_comments",
    "inline_annotations",
    "is_resolve_comment",
    "is_resolved_thread",
    "move_anchor",
    "new_draft",
    "pending_count",
    "put_pending",
    "remove_pending",
    "reopen_draft",
    "reply_draft",
    "resolution_reply",
    "select_line",
    "selection_range",
    "set_draft_text",
    "thread_members",
    "thread_root",
    "thread_root_id",
    "thread_rows",
    "thread_tip",
]
