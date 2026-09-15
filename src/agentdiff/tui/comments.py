from __future__ import annotations

from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum

from agentdiff.anchor import (
    RESOLVE_AUTHOR,
    Thread,
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
    Role,
    Side,
    new_comment_id,
)
from agentdiff.store.base import Store, StoreError
from agentdiff.tui.render import (
    DisplayLine,
    RenderedDiff,
    RowKind,
    line_index,
    line_number,
    line_side,
)

DEFAULT_AUTHOR = "reviewer"
DRIFTED_NOTE = "location not found in patch"


class DraftKind(str, Enum):
    NEW = "new"
    REPLY = "reply"
    REOPEN = "reopen"


@dataclass(frozen=True)
class Selection:
    """A display-line selection. ``anchor``/``cursor`` are display-line indices
    into ``RenderedDiff.lines``; ``side`` is the range's locked side or None
    while still neutral (grey context only). Neutral is transient and never
    persisted — it resolves to ``NEW`` when a comment is built. (R1/R2)
    """

    side: Side | None = None
    anchor: int | None = None
    cursor: int | None = None


def select_line(
    selection: Selection, index: int | None, side: Side | None = None
) -> Selection:
    """Collapse to a point at display-line ``index``; ``side`` is the line's
    own side (None = neutral). (R1)"""
    return replace(selection, side=side, anchor=index, cursor=index)


def side_compatible(locked: Side | None, incoming: Side | None) -> bool:
    """Grey (None) is compatible with anything; a locked side accepts only
    itself. (R2)"""
    return locked is None or incoming is None or locked is incoming


def step_to_compatible(
    rendered: RenderedDiff, start: int, direction: int, side: Side | None
) -> int | None:
    """The next display index strictly beyond ``start`` in ``direction``
    (``+1``/``-1``) whose line is compatible with the locked ``side`` (neutral
    or the same color). Opposite-color lines are skipped; ``None`` when there
    is none, so the cursor holds. (R2, revised by feedback)
    """
    index = start + direction
    while 0 <= index < len(rendered.lines):
        if side_compatible(side, line_side(rendered.lines[index])):
            return index
        index += direction
    return None


def extend_to(
    selection: Selection, index: int | None, side: Side | None = None
) -> Selection:
    """Extend the range to display-line ``index``. Refused (unchanged) when
    ``side`` is the opposite color; otherwise the first colored line locks the
    side. (R2)"""
    if selection.anchor is None:
        return select_line(selection, index, side)
    if not side_compatible(selection.side, side):
        return selection
    locked = selection.side if selection.side is not None else side
    return replace(selection, side=locked, cursor=index)


def resolve_side(side: Side | None) -> Side:
    """Neutral resolves to NEW when the comment is built. (R1/R2)"""
    return Side.NEW if side is None else side


def selection_range(rendered: RenderedDiff, selection: Selection) -> LineRange | None:
    """The concrete ``LineRange`` for the current selection, or None when empty.

    ``side`` is ``resolve_side(selection.side)``; start/end are the min/max model
    line numbers of the display lines in ``[anchor, cursor]`` on that side. Grey
    context lines carry both numbers, so a grey-then-red range yields OLD
    numbers. (R1/R2)
    """
    if selection.anchor is None or selection.cursor is None:
        return None
    side = resolve_side(selection.side)
    low, high = sorted((selection.anchor, selection.cursor))
    numbers = [
        number
        for index in range(low, high + 1)
        if 0 <= index < len(rendered.lines)
        for number in [line_number(rendered.lines[index], side)]
        if number is not None
    ]
    if not numbers:
        return None
    return LineRange(side=side, start=min(numbers), end=max(numbers))


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
    role: Role = Role.HUMAN,
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
        role=role,
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


def build_comment_view(
    comments: Sequence[Comment],
    change: Change,
    revision: str | None = None,
) -> CommentView:
    """Partition comments for the version being viewed.

    Only comments that belong to ``revision`` (default: the current version)
    are inline/resolved — resolved comments stay on the version they were made
    on and do not leak onto newer versions. (Feedback 5)
    """
    if revision is None:
        revision = change.head_revision
    inline_comments = [
        comment
        for comment in comments
        if comment.state is CommentState.ACTIVE and comment.revision == revision
    ]
    inline_ids = {comment.id for comment in inline_comments}
    replies_by_parent: dict[str, list[Comment]] = {}
    roots: list[Comment] = []
    for comment in inline_comments:
        if comment.in_reply_to is not None and comment.in_reply_to in inline_ids:
            replies_by_parent.setdefault(comment.in_reply_to, []).append(comment)
        else:
            roots.append(comment)

    def descendants(root_id: str) -> tuple[Comment, ...]:
        ordered: list[Comment] = []

        def visit(parent_id: str) -> None:
            for child in replies_by_parent.get(parent_id, ()):
                ordered.append(child)
                visit(child.id)

        visit(root_id)
        return tuple(ordered)

    inline = tuple(
        ThreadedComment(comment=root, replies=descendants(root.id)) for root in roots
    )
    resolved = tuple(
        comment
        for comment in comments
        if comment.state is CommentState.RESOLVED and comment.revision == revision
    )
    hidden = tuple(
        comment
        for comment in comments
        if comment.state is CommentState.CLOSED and comment.revision == revision
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
class ThreadRef:
    file_index: int
    file: str
    thread: Thread

    @property
    def root(self) -> Comment:
        return self.thread.root


def _thread_sort_key(ref: ThreadRef) -> tuple[int, int, int, datetime, str]:
    root = ref.root
    anchor = root.range
    if anchor is None:
        return (ref.file_index, 0, 0, root.created_at, root.id)
    return (ref.file_index, 1, anchor.start, root.created_at, root.id)


def thread_order(
    files: Sequence[str],
    comments: Sequence[Comment],
    *,
    revision: str | None = None,
) -> tuple[ThreadRef, ...]:
    """Every navigable thread ordered by (file order, anchor position). Pure. (R1)

    ``comments`` is the stored+pending pool; ``CLOSED`` comments are excluded
    (they are hidden, so they are not navigable) and, when ``revision`` is set,
    only members on that revision participate. A thread's anchor is its root's
    ``range``; a missing anchor (drifted / file-level) sorts first in its file so
    it matches its rendered row at the top. Threads whose file is not in ``files``
    are skipped (they never render). Ties break on ``(created_at, id)``.
    """
    pool = [
        comment
        for comment in comments
        if comment.state is not CommentState.CLOSED
        and (revision is None or comment.revision == revision)
    ]
    file_index = {path: index for index, path in enumerate(files)}
    refs: list[ThreadRef] = []
    for thread in group_threads(pool):
        index = file_index.get(thread.root.file)
        if index is None:
            continue
        refs.append(ThreadRef(file_index=index, file=thread.root.file, thread=thread))
    refs.sort(key=_thread_sort_key)
    return tuple(refs)


def thread_index(order: Sequence[ThreadRef], root_id: str | None) -> int | None:
    """Position of ``root_id`` in ``order``; None when absent/None. Pure. (R1)"""
    if root_id is None:
        return None
    for index, ref in enumerate(order):
        if ref.root.id == root_id:
            return index
    return None


def adjacent_thread(
    order: Sequence[ThreadRef], current_root_id: str | None, delta: int
) -> ThreadRef | None:
    """The thread ``delta`` steps (``+1``/``-1``) from ``current_root_id``.

    Clamps at both ends (no wrap). With no current thread, a forward step
    selects the first thread and a backward step the last. None when ``order``
    is empty. Pure. (R1)
    """
    if not order:
        return None
    index = thread_index(order, current_root_id)
    if index is None:
        return order[0] if delta > 0 else order[-1]
    target = max(0, min(len(order) - 1, index + delta))
    return order[target]


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
    view: CommentView,
    pending: PendingBuffer,
    file: str,
    *,
    revision: str | None = None,
) -> tuple[CommentAnnotation, ...]:
    pool: list[Comment] = []
    for thread in view.inline:
        if thread.comment.file == file:
            pool.append(thread.comment)
        pool.extend(reply for reply in thread.replies if reply.file == file)
    pool.extend(comment for comment in view.resolved if comment.file == file)
    pool.extend(
        comment
        for comment in pending.items
        if comment.file == file and (revision is None or comment.revision == revision)
    )
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
    PENDING = "pending"
    RESOLVED = "resolved"
    HUMAN = "human"
    AGENT = "agent"


class ThreadKind(str, Enum):
    PENDING = "pending"
    RESOLVED = "resolved"
    AWAITING_AGENT = "awaiting_agent"
    AWAITING_YOU = "awaiting_you"


def thread_kind(thread: Thread, pending_ids: Set[str] = frozenset()) -> ThreadKind:
    """A thread's conversation color from its derived state. Pure. (R2, R3)

    A pending tip (staged reply/comment) wins, then RESOLVED, then the last
    responder: human -> AWAITING_AGENT, agent -> AWAITING_YOU.
    """
    if thread.members[-1].id in pending_ids:
        return ThreadKind.PENDING
    if thread.state is ThreadState.RESOLVED:
        return ThreadKind.RESOLVED
    if thread.last_author is Role.HUMAN:
        return ThreadKind.AWAITING_AGENT
    return ThreadKind.AWAITING_YOU


@dataclass(frozen=True)
class ThreadMarker:
    row: int
    kind: ThreadKind
    root: str


def marker_row(anchor: int, total_rows: int, height: int) -> int:
    """Proportional marker row: anchor * (height-1) // (total_rows-1), clamped
    to [0, height-1]; 0 when the column or content is degenerate. Pure. (R2)"""
    if height <= 1 or total_rows <= 1:
        return 0
    row = anchor * (height - 1) // (total_rows - 1)
    return max(0, min(height - 1, row))


def thread_markers(
    anchors: Sequence[tuple[int, ThreadKind, str]],
    *,
    total_rows: int,
    height: int,
) -> tuple[ThreadMarker, ...]:
    """Map (anchor display row, thread kind, root id) triples to overview
    markers, preserving order. Pure. (R2)"""
    return tuple(
        ThreadMarker(row=marker_row(anchor, total_rows, height), kind=kind, root=root)
        for anchor, kind, root in anchors
    )


@dataclass(frozen=True)
class AnchorBox:
    start: int
    end: int
    kind: CommentKind


_KIND_PRECEDENCE = {
    CommentKind.HUMAN: 0,
    CommentKind.AGENT: 0,
    CommentKind.RESOLVED: 2,
    CommentKind.PENDING: 3,
}


def annotation_kind(annotation: CommentAnnotation) -> CommentKind:
    """Per-comment color: pending / resolved override, else the comment's own
    role. Pure. (R3)"""
    if annotation.pending:
        return CommentKind.PENDING
    if annotation.resolved:
        return CommentKind.RESOLVED
    if annotation.comment.role is Role.AGENT:
        return CommentKind.AGENT
    return CommentKind.HUMAN


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
        kinds.append(annotation_kind(annotation))
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
    human_last: int = 0
    agent_last: int = 0


def comment_counts(
    view: CommentView,
    pending: PendingBuffer,
    *,
    revision: str | None = None,
) -> dict[str, FileCommentCounts]:
    """Per-file draft / resolved / human-last / agent-last counts. Pure.

    ``draft`` counts pending comments; ``resolved`` counts conversations whose
    latest member is RESOLVED, and open conversations are routed to
    ``human_last``/``agent_last`` by their latest member's role. A conversation
    with a newer pending reply is a draft, not resolved. Counts are scoped to
    ``revision`` (the version in view) so they follow version navigation.
    """
    pending_items = [
        comment
        for comment in pending.items
        if revision is None or comment.revision == revision
    ]
    pool: list[Comment] = []
    for thread in view.inline:
        pool.append(thread.comment)
        pool.extend(thread.replies)
    pool.extend(view.resolved)
    pool.extend(pending_items)
    pending_ids = {comment.id for comment in pending_items}

    draft: dict[str, int] = {}
    resolved: dict[str, int] = {}
    human_last: dict[str, int] = {}
    agent_last: dict[str, int] = {}
    for comment in pending_items:
        draft[comment.file] = draft.get(comment.file, 0) + 1
    for thread in group_threads(pool):
        latest = thread.members[-1]
        if latest.id in pending_ids:
            continue
        if thread.state is ThreadState.RESOLVED:
            resolved[latest.file] = resolved.get(latest.file, 0) + 1
        elif thread.state is ThreadState.OPEN:
            if thread.last_author is Role.HUMAN:
                human_last[latest.file] = human_last.get(latest.file, 0) + 1
            else:
                agent_last[latest.file] = agent_last.get(latest.file, 0) + 1

    files = set(draft) | set(resolved) | set(human_last) | set(agent_last)
    return {
        file: FileCommentCounts(
            draft=draft.get(file, 0),
            resolved=resolved.get(file, 0),
            human_last=human_last.get(file, 0),
            agent_last=agent_last.get(file, 0),
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
    "ThreadKind",
    "ThreadMarker",
    "ThreadRef",
    "adjacent_thread",
    "anchor_boxes",
    "annotate",
    "annotation_kind",
    "build_comment_view",
    "comment_counts",
    "draft_to_comment",
    "extend_to",
    "flush_comments",
    "inline_annotations",
    "is_resolve_comment",
    "is_resolved_thread",
    "marker_row",
    "move_anchor",
    "new_draft",
    "pending_count",
    "put_pending",
    "remove_pending",
    "reopen_draft",
    "reply_draft",
    "resolution_reply",
    "resolve_side",
    "select_line",
    "selection_range",
    "set_draft_text",
    "side_compatible",
    "step_to_compatible",
    "thread_index",
    "thread_kind",
    "thread_markers",
    "thread_members",
    "thread_order",
    "thread_root",
    "thread_root_id",
    "thread_rows",
    "thread_tip",
]
