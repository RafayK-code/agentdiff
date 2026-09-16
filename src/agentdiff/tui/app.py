from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import ClassVar

from rich.style import Style
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.css.query import NoMatches
from textual.events import Click, Key, Resize, TextSelected
from textual.widgets import Button, Footer, Input, Label, ListItem, ListView, Static

from agentdiff.anchor import reanchor_thread
from agentdiff.model.types import Comment, Role, Side
from agentdiff.store import Store, StoreError, create_store
from agentdiff.tui.comments import (
    DEFAULT_AUTHOR,
    AnchorBox,
    CommentAnnotation,
    CommentKind,
    CommentView,
    DraftKind,
    EditorDraft,
    FileCommentCounts,
    PendingBuffer,
    Selection,
    ThreadKind,
    ThreadMarker,
    ThreadRef,
    adjacent_thread,
    anchor_boxes,
    annotate,
    annotation_kind,
    build_comment_view,
    comment_counts,
    draft_to_comment,
    extend_to,
    flush_comments,
    inline_annotations,
    is_resolved_thread,
    move_anchor,
    new_draft,
    pending_count,
    put_pending,
    remove_pending,
    reopen_draft,
    reply_draft,
    resolution_reply,
    select_line,
    selection_range,
    set_draft_text,
    step_to_compatible,
    thread_index,
    thread_kind,
    thread_markers,
    thread_members,
    thread_order,
    thread_root_id,
    thread_rows,
    thread_tip,
)
from agentdiff.tui.help import HelpScreen
from agentdiff.tui.render import (
    CellKind,
    Column,
    DiffView,
    DisplayLine,
    RenderedDiff,
    RowKind,
    ViewMode,
    expand_all_view,
    expand_view,
    hunk_at,
    line_index,
    line_side,
    make_diff_view,
    render_view,
)
from agentdiff.tui.session import load_comments, load_shell_state
from agentdiff.tui.state import (
    ShellState,
    format_file,
    format_header,
    is_current_version,
    select_file,
    select_version,
    selected_version,
)

_FILE_HEADER_STYLE = Style(color="#569cd6", bold=True)
_HUNK_HEADER_STYLE = Style(color="#4ec9b0")
_FOCUSED_HUNK_STYLE = Style(color="#ffffff", bgcolor="#264f78", bold=True)
_CONTEXT_STYLE = Style(color="#d4d4d4")
_GUTTER_STYLE = Style(color="#6e7681")
_ADD_LINE_STYLE = Style(bgcolor="#204a2e")
_DEL_LINE_STYLE = Style(bgcolor="#4a2020")
_ADD_SPAN_STYLE = Style(bgcolor="#2ea043")
_DEL_SPAN_STYLE = Style(bgcolor="#c93c37")
_SKIP_STYLE = Style(color="#808080", italic=True)
_NOTE_STYLE = Style(color="#808080", italic=True)
_COMMENT_STYLE = Style(color="#c586c0")
_PENDING_COMMENT_STYLE = Style(color="#dcdcaa", italic=True)
_RESOLVED_COMMENT_STYLE = Style(color="#4ec9b0", italic=True)
_AWAITING_AGENT_COMMENT_STYLE = Style(color="#e06c75", bold=True)
_AWAITING_YOU_COMMENT_STYLE = Style(color="#61afef", bold=True)
_HUMAN_COMMENT_STYLE = _AWAITING_AGENT_COMMENT_STYLE
_AGENT_COMMENT_STYLE = _AWAITING_YOU_COMMENT_STYLE
_SELECTED_LINE_STYLE = Style(bgcolor="#3a3a3a")
_SELECTED_ADD_STYLE = Style(bgcolor="#2d6a3f")
_SELECTED_DEL_STYLE = Style(bgcolor="#6a2d2d")

_MARKERS = {CellKind.CTX: " ", CellKind.ADD: "+", CellKind.DEL: "-"}


def _gutter(number: int | None) -> str:
    return f"{number:>4}" if number is not None else "    "


def _clamp(value: int, count: int) -> int:
    if count <= 0:
        return 0
    return max(0, min(count - 1, value))


def _box_style(kind: CommentKind) -> Style:
    if kind is CommentKind.RESOLVED:
        return _RESOLVED_COMMENT_STYLE
    if kind is CommentKind.PENDING:
        return _PENDING_COMMENT_STYLE
    if kind is CommentKind.AGENT:
        return _AGENT_COMMENT_STYLE
    if kind is CommentKind.HUMAN:
        return _HUMAN_COMMENT_STYLE
    return _COMMENT_STYLE


def _thread_style(kind: ThreadKind) -> Style:
    if kind is ThreadKind.RESOLVED:
        return _RESOLVED_COMMENT_STYLE
    if kind is ThreadKind.PENDING:
        return _PENDING_COMMENT_STYLE
    if kind is ThreadKind.AWAITING_YOU:
        return _AWAITING_YOU_COMMENT_STYLE
    return _AWAITING_AGENT_COMMENT_STYLE


class _AnchorLabel(Static):
    can_focus = True


class _DiffPane(ScrollableContainer):
    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        super().watch_scroll_y(old_value, new_value)
        app = self.app
        if isinstance(app, AgentdiffApp) and app.is_mounted:
            app._paint_markers()


class AgentdiffApp(App[None]):
    CSS = """
    #header {
        dock: top;
        height: 3;
        align: center middle;
    }
    #header-label {
        width: 1fr;
        height: 3;
        content-align: center middle;
    }
    #files-button {
        min-width: 7;
    }
    #prev-version, #next-version {
        min-width: 5;
    }
    #help-button {
        min-width: 3;
    }
    #body {
        height: 1fr;
    }
    #files {
        width: 30%;
        border: round #303030;
    }
    #files:focus {
        border: round #4ec9b0;
    }
    .file-row {
        height: 1;
    }
    .file-name {
        width: 1fr;
        text-overflow: ellipsis;
    }
    .file-counts {
        width: auto;
        height: 1;
        padding: 0 0 0 1;
    }
    #diff-column {
        width: 1fr;
    }
    #meta {
        height: 1;
    }
    #thread-indicator {
        width: auto;
        height: 1;
        padding: 0 2 0 0;
        color: #9cdcfe;
    }
    #status {
        width: 1fr;
        height: 1;
        color: #dcdcaa;
    }
    #diff-area {
        height: 1fr;
    }
    #diff-pane {
        width: 1fr;
        height: 1fr;
        border: round #303030;
    }
    #diff-pane:focus {
        border: round #4ec9b0;
    }
    #markers {
        width: 1;
        height: 1fr;
        padding-top: 1;
    }
    #diff {
        width: auto;
        text-wrap: nowrap;
    }
    #editor {
        display: none;
        height: 6;
        border: round #4ec9b0;
        padding: 0 1;
    }
    #editor-anchor:focus {
        background: #264f78;
    }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit", show=False),
        Binding("j", "cursor_down", "Down"),
        Binding("k", "cursor_up", "Up"),
        Binding("tab", "toggle_focus", "Switch focus"),
        Binding("f", "focus_files", "Files"),
        Binding("n", "next_thread", "Next thread"),
        Binding("p", "prev_thread", "Prev thread"),
        Binding("]", "expand_down", "Expand down"),
        Binding("+", "expand_down", "Expand down", show=False),
        Binding("=", "expand_down", "Expand down", show=False),
        Binding("[", "expand_up", "Expand up"),
        Binding("e", "expand_all", "Expand all"),
        Binding("h", "prev_version", "Prev version"),
        Binding("l", "next_version", "Next version"),
        Binding("c", "new_comment", "Comment"),
        Binding("F", "new_file_comment", "File comment"),
        Binding("r", "reply", "Reply"),
        Binding("s", "resolve", "Resolve"),
        Binding("x", "close_comment", "Close"),
        Binding("C", "confirm_comments", "Confirm"),
        Binding("v", "toggle_range", "Range"),
        Binding("d", "remove_pending", "Remove"),
        Binding("?", "show_help", "Help"),
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, state: ShellState, store: Store | None = None) -> None:
        super().__init__()
        self._state = state
        self._store = store
        self._view_mode = ViewMode.UNIFIED
        self._view = self._build_view(state.selected)
        self._selected_line = 0
        self._rendered: RenderedDiff | None = None
        self._base_text: Text | None = None
        self._base_width = -1
        self._line_ranges: list[tuple[int, int]] = []
        self._line_to_row: dict[int, int] = {}
        self._row_to_line: list[int | None] = []
        self._comment_rows: dict[int, Comment] = {}
        self._annotations_by_line: dict[int, CommentAnnotation] = {}
        self._pending = PendingBuffer()
        self._draft: EditorDraft | None = None
        self._selection = Selection()
        self._range_mode = False
        self._anchor_boxes: tuple[AnchorBox, ...] = ()
        self._comments = tuple(state.comments)
        self._view_state = self._build_comment_view()
        self._status = ""

    def _build_comment_view(self) -> CommentView:
        change = self._state.change
        version = selected_version(self._state)
        if change is None or version is None:
            return CommentView(inline=(), resolved=(), hidden=())
        return build_comment_view(self._comments, change, version.revision)

    def _current_file_path(self) -> str | None:
        version = selected_version(self._state)
        if version is None or not 0 <= self._state.selected < len(version.files):
            return None
        return version.files[self._state.selected].path

    def _build_view(self, index: int) -> DiffView | None:
        version = selected_version(self._state)
        if version is None or not 0 <= index < len(version.files):
            return None
        entry = self._state.files[index]
        content = None
        if is_current_version(self._state) and index < len(self._state.contents):
            content = self._state.contents[index]
        return make_diff_view(
            version.files[index], header=format_file(entry), content=content
        )

    def compose(self) -> ComposeResult:
        with Horizontal(id="header"):
            yield Button("files", id="files-button")
            yield Button("\u2039", id="prev-version")
            yield Static(format_header(self._state), id="header-label")
            yield Button("\u203a", id="next-version")
            yield Button("?", id="help-button")
        with Horizontal(id="body"):
            with ListView(id="files"):
                for entry in self._state.files:
                    yield ListItem(Label(format_file(entry)))
            with Vertical(id="diff-column"):
                with Horizontal(id="meta"):
                    yield Static("", id="thread-indicator")
                    yield Static("", id="status")
                with Horizontal(id="diff-area"):
                    with _DiffPane(id="diff-pane"):
                        yield Static("", id="diff")
                    yield Static("", id="markers")
                with Vertical(id="editor"):
                    yield _AnchorLabel("", id="editor-anchor")
                    yield Input(id="editor-text")
        yield Footer()

    def on_mount(self) -> None:
        if self._state.files:
            self.query_one("#files", ListView).focus()
        self._refresh_header()
        self._refresh_files()
        self._refresh_diff(focus_hunk=True)

    def _refresh_header(self) -> None:
        self.query_one("#header-label", Static).update(format_header(self._state))
        change = self._state.change
        count = len(change.versions) if change is not None else 0
        self.query_one("#prev-version", Button).disabled = (
            self._state.version_index <= 0
        )
        self.query_one("#next-version", Button).disabled = (
            count == 0 or self._state.version_index >= count - 1
        )

    def _set_index(self, index: int) -> None:
        self._state = select_file(self._state, index - self._state.selected)
        self._view = self._build_view(self._state.selected)
        self._selected_line = 0
        self._refresh_diff(focus_hunk=True)

    def _refresh_files(self) -> None:
        files = self.query_one("#files", ListView)
        files.clear()
        version = selected_version(self._state)
        counts = comment_counts(
            self._view_state,
            self._pending,
            revision=version.revision if version is not None else None,
        )
        for entry in self._state.files:
            entry_counts = counts.get(entry.path, FileCommentCounts())
            counts_text = Text()
            if entry_counts.draft:
                counts_text.append(
                    f"{entry_counts.draft}", _thread_style(ThreadKind.PENDING)
                )
            if entry_counts.resolved:
                counts_text.append(
                    f" {entry_counts.resolved}", _thread_style(ThreadKind.RESOLVED)
                )
            if entry_counts.human_last:
                counts_text.append(
                    f" {entry_counts.human_last}",
                    _thread_style(ThreadKind.AWAITING_AGENT),
                )
            if entry_counts.agent_last:
                counts_text.append(
                    f" {entry_counts.agent_last}",
                    _thread_style(ThreadKind.AWAITING_YOU),
                )
            row = Horizontal(
                Label(Text(format_file(entry)), classes="file-name"),
                Label(counts_text, classes="file-counts"),
                classes="file-row",
            )
            files.append(ListItem(row))

    def _refresh_diff(
        self, *, focus_hunk: bool = False, preserve_scroll: bool = False
    ) -> None:
        diff = self.query_one("#diff", Static)
        pane = self.query_one("#diff-pane", ScrollableContainer)
        scroll_offset = pane.scroll_offset
        if self._view is None:
            self._rendered = None
            self._base_text = None
            self._line_ranges = []
            self._line_to_row = {}
            self._row_to_line = []
            self._comment_rows = {}
            self._annotations_by_line = {}
            self._anchor_boxes = ()
            diff.update(self._state.message or "")
            self._refresh_thread_indicator()
            self._paint_markers()
            self._refresh_status()
            return
        base = render_view(self._view, self._view_mode)
        path = self._current_file_path()
        version = selected_version(self._state)
        annotations = (
            inline_annotations(
                self._view_state,
                self._pending,
                path,
                revision=version.revision if version is not None else None,
            )
            if path is not None
            else ()
        )
        annotated = annotate(base, annotations)
        rendered = annotated.rendered
        self._comment_rows = annotated.comment_rows
        by_id = {annotation.comment.id: annotation for annotation in annotations}
        self._annotations_by_line = {
            index: by_id[comment.id]
            for index, comment in annotated.comment_rows.items()
            if comment.id in by_id
        }
        self._rendered = rendered
        self._anchor_boxes = anchor_boxes(rendered, annotations)
        self._base_text = None
        if focus_hunk and rendered.hunk_starts:
            index = min(self._view.hunk_index, len(rendered.hunk_starts) - 1)
            self._selected_line = rendered.hunk_starts[index]
        self._selected_line = _clamp(self._selected_line, len(rendered.lines))
        self._sync_selection()
        self._paint()
        self._refresh_thread_indicator()
        self._paint_markers()
        self._refresh_status()
        if preserve_scroll:
            pane.scroll_to(x=scroll_offset.x, y=scroll_offset.y, animate=False)
        else:
            self._scroll_to_hunk(rendered)

    def _refresh_status(self) -> None:
        parts: list[str] = []
        if self._status:
            parts.append(self._status)
        parts.append(f"pending: {pending_count(self._pending)}")
        if self._state.change is not None and not is_current_version(self._state):
            parts.append("history (read-only)")
        self.query_one("#status", Static).update("  ".join(parts))

    def _sync_selection(self) -> None:
        index = self._selected_line
        side = self._side_at(index)
        if self._range_mode:
            self._selection = extend_to(self._selection, index, side)
        else:
            self._selection = select_line(self._selection, index, side)

    def _side_at(self, index: int) -> Side | None:
        if self._rendered is None or not 0 <= index < len(self._rendered.lines):
            return None
        return line_side(self._rendered.lines[index])

    def _pane_width(self) -> int:
        pane = self.query_one("#diff-pane", ScrollableContainer)
        return max(0, pane.content_region.width)

    def _paint(self, *, layout: bool = True) -> None:
        if self._rendered is None:
            return
        width = self._pane_width()
        if self._base_text is None or self._base_width != width:
            self._base_text = self._to_text(self._rendered, min_width=width)
            self._base_width = width
        text = self._base_text.copy()
        for index in self._highlight_indices():
            row = self._line_to_row.get(index)
            if row is not None and 0 <= row < len(self._line_ranges):
                start, end = self._line_ranges[row]
                text.stylize(self._style_for(index), start, end)
        self.query_one("#diff", Static).update(text, layout=layout)

    def _highlight_indices(self) -> list[int]:
        if self._rendered is None:
            return []
        comment = self._selected_comment()
        if comment is not None:
            rows = thread_rows(self._comment_rows, comment, self._pool())
            if rows:
                return list(rows)
        if (
            self._range_mode
            and self._selection.anchor is not None
            and self._selection.cursor is not None
        ):
            low, high = sorted((self._selection.anchor, self._selection.cursor))
            return list(range(low, high + 1))
        return [self._selected_line]

    def _pool(self) -> list[Comment]:
        return [*self._comments, *self._pending.items]

    def _style_for(self, index: int) -> Style:
        if self._rendered is not None and index < len(self._rendered.lines):
            line = self._rendered.lines[index]
            for column in line.columns:
                if column.kind is CellKind.ADD:
                    return _SELECTED_ADD_STYLE
                if column.kind is CellKind.DEL:
                    return _SELECTED_DEL_STYLE
        return _SELECTED_LINE_STYLE

    def _move_line(self, delta: int) -> None:
        if self._rendered is None or not self._rendered.lines:
            return
        if self._range_mode:
            target = step_to_compatible(
                self._rendered, self._selected_line, delta, self._selection.side
            )
            if target is None:
                return
        else:
            target = _clamp(self._selected_line + delta, len(self._rendered.lines))
        if target == self._selected_line:
            return
        self._selected_line = target
        self._sync_selection()
        self._sync_hunk_index()
        self._paint(layout=False)
        self._ensure_line_visible()
        self._refresh_thread_indicator()

    def _ensure_line_visible(self) -> None:
        pane = self.query_one("#diff-pane", ScrollableContainer)
        height = pane.scrollable_content_region.height
        if height <= 0:
            return
        row = self._line_to_row.get(self._selected_line, self._selected_line)
        offset = int(pane.scroll_offset.y)
        if row < offset:
            pane.scroll_to(y=row, animate=False)
        elif row >= offset + height:
            pane.scroll_to(y=row - height + 1, animate=False)

    def _diff_focused(self) -> bool:
        pane = self.query_one("#diff-pane", ScrollableContainer)
        focused = self.focused
        return focused is not None and (focused is pane or pane in focused.ancestors)

    def _scroll_to_hunk(self, rendered: RenderedDiff) -> None:
        if self._view is None or not rendered.hunk_starts:
            return
        index = min(self._view.hunk_index, len(rendered.hunk_starts) - 1)
        line = rendered.hunk_starts[index]
        pane = self.query_one("#diff-pane", ScrollableContainer)
        pane.scroll_to(y=self._line_to_row.get(line, line), animate=False)

    def _to_text(self, rendered: RenderedDiff, *, min_width: int = 0) -> Text:
        line_box: dict[int, AnchorBox] = {}
        box_starts: set[int] = set()
        box_ends: set[int] = set()
        for box in self._anchor_boxes:
            for index in range(box.start, box.end + 1):
                line_box[index] = box
            box_starts.add(box.start)
            box_ends.add(box.end)

        pieces: list[Text] = []
        for index, line in enumerate(rendered.lines):
            piece = Text()
            box = line_box.get(index)
            if box is not None:
                piece.append("\u2502 ", _box_style(box.kind))
            else:
                piece.append("  ")
            self._append_line(piece, line, index)
            pieces.append(piece)

        widths = [piece.cell_len for piece in pieces]
        widths.append(min_width)
        width = max(widths)

        text = Text()
        ranges: list[tuple[int, int]] = []
        row_to_line: list[int | None] = []
        line_to_row: dict[int, int] = {}

        def emit(piece: Text, rendered_index: int | None) -> None:
            if ranges:
                text.append("\n")
            start = len(text)
            text.append(piece)
            pad = width - piece.cell_len
            if pad > 0:
                text.append(" " * pad)
            ranges.append((start, len(text)))
            row_to_line.append(rendered_index)
            if rendered_index is not None:
                line_to_row[rendered_index] = len(ranges) - 1

        for index, piece in enumerate(pieces):
            box = line_box.get(index)
            if index in box_starts:
                assert box is not None
                style = _box_style(box.kind)
                border = Text()
                border.append("\u250c" + "\u2500" * max(0, width - 1) + "\u2510", style)
                emit(border, None)
            if box is not None:
                styled = piece.copy()
                style = _box_style(box.kind)
                styled.append(" " * max(0, width - piece.cell_len), style)
                styled.append("\u2502", style)
                emit(styled, index)
            else:
                emit(piece, index)
            if index in box_ends:
                assert box is not None
                style = _box_style(box.kind)
                border = Text()
                border.append("\u2514" + "\u2500" * max(0, width - 1) + "\u2518", style)
                emit(border, None)

        self._line_ranges = ranges
        self._row_to_line = row_to_line
        self._line_to_row = line_to_row
        return text

    def _append_line(self, text: Text, line: DisplayLine, index: int) -> None:
        if line.kind is RowKind.FILE_HEADER:
            text.append(line.text, _FILE_HEADER_STYLE)
        elif line.kind is RowKind.HUNK_HEADER:
            focused = (
                self._view is not None and line.hunk_index == self._view.hunk_index
            )
            style = _FOCUSED_HUNK_STYLE if focused else _HUNK_HEADER_STYLE
            text.append(line.text, style)
        elif line.kind is RowKind.SKIP:
            text.append(line.text, _SKIP_STYLE)
        elif line.kind is RowKind.NOTE:
            text.append(line.text, _NOTE_STYLE)
        elif line.kind is RowKind.COMMENT:
            annotation = self._annotations_by_line.get(index)
            style = (
                _box_style(annotation_kind(annotation))
                if annotation is not None
                else _COMMENT_STYLE
            )
            text.append(line.text, style)
        else:
            for column in line.columns:
                self._append_column(text, column)

    def _append_column(self, text: Text, column: Column) -> None:
        if column.kind is CellKind.ADD:
            base = _ADD_LINE_STYLE
        elif column.kind is CellKind.DEL:
            base = _DEL_LINE_STYLE
        else:
            base = _CONTEXT_STYLE
        for number in column.gutters:
            text.append(_gutter(number), _GUTTER_STYLE)
            text.append(" ", _GUTTER_STYLE)
        text.append(f" {_MARKERS[column.kind]} ", base)
        position = 0
        for span in sorted(column.spans, key=lambda item: item.start):
            if span.start > position:
                text.append(column.text[position : span.start], base)
            span_style = _ADD_SPAN_STYLE if span.kind == "add" else _DEL_SPAN_STYLE
            text.append(column.text[span.start : span.end], span_style)
            position = span.end
        if position < len(column.text):
            text.append(column.text[position:], base)
        text.append(" ", base)

    def action_cursor_down(self) -> None:
        if self._diff_focused():
            self._move_line(1)
        else:
            self.query_one("#files", ListView).action_cursor_down()

    def action_cursor_up(self) -> None:
        if self._diff_focused():
            self._move_line(-1)
        else:
            self.query_one("#files", ListView).action_cursor_up()

    def action_toggle_focus(self) -> None:
        if self._diff_focused():
            self.query_one("#files", ListView).focus()
        else:
            self.query_one("#diff-pane", ScrollableContainer).focus()

    def action_focus_files(self) -> None:
        self.query_one("#files", ListView).focus()

    def action_show_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_next_thread(self) -> None:
        self._goto_thread(+1)

    def action_prev_thread(self) -> None:
        self._goto_thread(-1)

    def _thread_order(self) -> tuple[ThreadRef, ...]:
        version = selected_version(self._state)
        if version is None:
            return ()
        return thread_order(
            [file.path for file in version.files],
            self._pool(),
            revision=version.revision,
        )

    def _current_thread_id(self) -> str | None:
        comment = self._selected_comment()
        if comment is None:
            return None
        return thread_root_id(comment, self._pool())

    def _select_thread(self, root_id: str) -> None:
        pool = self._pool()
        for row, comment in self._comment_rows.items():
            if thread_root_id(comment, pool) == root_id:
                self._selected_line = row
                break
        else:
            return
        self._sync_selection()
        self._sync_hunk_index()
        self._paint(layout=False)
        self._ensure_line_visible()
        self._refresh_thread_indicator()

    def _goto_thread(self, delta: int) -> None:
        ref = adjacent_thread(self._thread_order(), self._current_thread_id(), delta)
        if ref is None:
            return
        if ref.file_index != self._state.selected:
            self._set_index(ref.file_index)
            self.query_one("#files", ListView).index = ref.file_index
        self._select_thread(ref.root.id)

    def _sync_hunk_index(self) -> None:
        if self._view is None or self._rendered is None:
            return
        index = hunk_at(self._rendered, self._selected_line) or 0
        if index != self._view.hunk_index:
            self._view = replace(self._view, hunk_index=index)
            self._base_text = None

    def _refresh_thread_indicator(self) -> None:
        order = self._thread_order()
        indicator = self.query_one("#thread-indicator", Static)
        if not order:
            indicator.update("")
            return
        index = thread_index(order, self._current_thread_id())
        if index is None:
            indicator.update(f"{len(order)} threads")
        else:
            indicator.update(f"thread {index + 1} of {len(order)}")

    def _marker_height(self) -> int:
        pane = self.query_one("#diff-pane", ScrollableContainer)
        return pane.scrollable_content_region.height

    def _current_file_markers(self) -> tuple[ThreadMarker, ...]:
        if self._rendered is None:
            return ()
        version = selected_version(self._state)
        path = self._current_file_path()
        if version is None or path is None:
            return ()
        pool = self._pool()
        pending_ids = {comment.id for comment in self._pending.items}
        anchors: list[tuple[int, ThreadKind, str]] = []
        for ref in thread_order(
            [file.path for file in version.files], pool, revision=version.revision
        ):
            if ref.file != path:
                continue
            rows = [
                self._line_to_row[row]
                for row, comment in self._comment_rows.items()
                if thread_root_id(comment, pool) == ref.root.id
                and row in self._line_to_row
            ]
            if not rows:
                continue
            anchors.append(
                (min(rows), thread_kind(ref.thread, pending_ids), ref.root.id)
            )
        return thread_markers(
            anchors,
            total_rows=len(self._line_ranges),
            height=self._marker_height(),
        )

    def _paint_markers(self) -> None:
        if not self.is_mounted or self._rendered is None:
            return
        try:
            widget = self.query_one("#markers", Static)
        except NoMatches:
            return
        height = self._marker_height()
        if height <= 0:
            widget.update("")
            return
        by_row = {marker.row: marker for marker in self._current_file_markers()}
        rows: list[Text] = []
        for row in range(height):
            line = Text()
            marker = by_row.get(row)
            if marker is not None:
                line.append("\u2588", _thread_style(marker.kind))
            rows.append(line)
        widget.update(Text("\n").join(rows))

    def action_expand_down(self) -> None:
        if self._view is None:
            return
        view = expand_view(self._view, direction="down")
        if view is not self._view:
            self._view = view
            self._refresh_diff()

    def action_expand_up(self) -> None:
        if self._view is None:
            return
        view = expand_view(self._view, direction="up")
        if view is not self._view:
            self._view = view
            self._refresh_diff()

    def action_expand_all(self) -> None:
        comment = self._selected_comment()
        if comment is not None and any(
            item.id == comment.id for item in self._pending.items
        ):
            self._edit_pending(comment)
            return
        if self._view is None:
            return
        view = expand_all_view(self._view)
        if view is not self._view:
            self._view = view
            self._refresh_diff()

    def _select_version(self, delta: int) -> None:
        updated = select_version(self._state, delta)
        if updated is self._state:
            return
        self._state = updated
        self._selection = Selection()
        self._range_mode = False
        self._view = self._build_view(self._state.selected)
        self._view_state = self._build_comment_view()
        self._selected_line = 0
        self._refresh_header()
        self._refresh_files()
        self._refresh_diff(focus_hunk=True)

    def action_prev_version(self) -> None:
        self._select_version(-1)

    def action_next_version(self) -> None:
        self._select_version(+1)

    def _can_author(self) -> bool:
        if self._view is None or self._state.change is None:
            return False
        if not is_current_version(self._state):
            self._status = "history is read-only"
            self._refresh_status()
            return False
        return True

    def _selected_comment(self) -> Comment | None:
        return self._comment_rows.get(self._selected_line)

    def action_toggle_range(self) -> None:
        self._range_mode = not self._range_mode
        self._selection = select_line(
            self._selection, self._selected_line, self._side_at(self._selected_line)
        )
        self._status = "range selection on" if self._range_mode else "range off"
        self._refresh_status()
        self._paint(layout=False)

    def action_new_comment(self) -> None:
        if not self._can_author():
            return
        path = self._current_file_path()
        line_range = (
            selection_range(self._rendered, self._selection)
            if self._rendered is not None
            else None
        )
        if path is None or line_range is None:
            self._status = "select a line to comment on"
            self._refresh_status()
            return
        self._range_mode = False
        self._selection = select_line(
            self._selection, self._selected_line, self._side_at(self._selected_line)
        )
        self._open_editor(new_draft(path, line_range))

    def action_new_file_comment(self) -> None:
        if not self._can_author():
            return
        path = self._current_file_path()
        if path is None:
            self._status = "select a file to comment on"
            self._refresh_status()
            return
        self._range_mode = False
        self._selection = select_line(
            self._selection, self._selected_line, self._side_at(self._selected_line)
        )
        self._open_editor(new_draft(path, None))

    def action_reply(self) -> None:
        # Replying is allowed on any version (it is how you reopen a resolved
        # thread); only *new* comments are restricted to the current version.
        if self._view is None or self._state.change is None:
            return
        comment = self._selected_comment()
        change = self._state.change
        if comment is None or change is None:
            self._status = "select a comment to reply to"
            self._refresh_status()
            return
        pool = self._pool()
        if is_resolved_thread(comment, pool):
            draft = reopen_draft(comment, pool, change, author=DEFAULT_AUTHOR)
            if self._store is not None:
                for member in reanchor_thread(
                    comment, change, pool, anchor=draft.anchor
                ):
                    try:
                        self._store.update_comment(member)
                    except StoreError:
                        break
                self._reload_comments()
            self._open_editor(draft)
            return
        self._open_editor(reply_draft(thread_tip(comment, pool)))

    def action_resolve(self) -> None:
        if not self._can_author():
            return
        comment = self._selected_comment()
        change = self._state.change
        if comment is None or self._store is None or change is None:
            self._status = "select a comment to resolve"
            self._refresh_status()
            return
        pool = self._pool()
        if is_resolved_thread(comment, pool):
            self._status = "already resolved"
            self._refresh_status()
            return
        try:
            self._store.add_comment(
                resolution_reply(thread_tip(comment, pool), change, role=Role.HUMAN)
            )
        except StoreError as exc:
            self._status = f"store error: {exc}"
            self._refresh_status()
            return
        self._status = "resolved"
        self._reload_comments()

    def action_close_comment(self) -> None:
        # Closing is allowed on any version (like replying/reopening); only
        # *new* comments are restricted to the current version.
        comment = self._selected_comment()
        if comment is None or self._store is None:
            self._status = "select a comment to close"
            self._refresh_status()
            return
        pending_ids = {item.id for item in self._pending.items}
        members = thread_members(comment, self._pool())
        try:
            for member in members:
                if member.id not in pending_ids:
                    self._store.close_comment(member.id)
        except StoreError as exc:
            self._status = f"store error: {exc}"
            self._refresh_status()
            return
        for member in members:
            if member.id in pending_ids:
                self._pending = remove_pending(self._pending, member.id)
        self._status = f"closed {len(members)} comment(s)"
        self._reload_comments()

    def action_confirm_comments(self) -> None:
        if self._store is None or not self._can_author():
            return
        result = flush_comments(self._pending, self._store)
        self._pending = PendingBuffer(items=result.remaining)
        if result.error is not None:
            self._status = f"store error: {result.error}"
        else:
            self._status = f"confirmed {len(result.written)} comment(s)"
        self._reload_comments()

    def action_remove_pending(self) -> None:
        if not self._can_author():
            return
        comment = self._selected_comment()
        if comment is None:
            return
        self._pending = remove_pending(self._pending, comment.id)
        self._status = "pending removed"
        self._refresh_files()
        self._refresh_diff(preserve_scroll=True)

    def _edit_pending(self, comment: Comment) -> None:
        kind = DraftKind.REPLY if comment.in_reply_to else DraftKind.NEW
        self._open_editor(
            EditorDraft(
                file=comment.file,
                kind=kind,
                anchor=comment.range,
                text=comment.text,
                in_reply_to=comment.in_reply_to,
                drifted=comment.drifted,
                editing_id=comment.id,
            )
        )

    def _open_editor(self, draft: EditorDraft) -> None:
        self._draft = draft
        self.query_one("#editor", Vertical).styles.display = "block"
        self._refresh_editor_anchor()
        text_input = self.query_one("#editor-text", Input)
        text_input.value = draft.text
        text_input.focus()

    def _refresh_editor_anchor(self) -> None:
        draft = self._draft
        if draft is None:
            return
        anchor = draft.anchor
        location = (
            f"{draft.file}:{anchor.start}-{anchor.end}"
            if anchor is not None
            else f"{draft.file} (file-level)"
        )
        quoted = f"  \u201c{draft.quoted}\u201d" if draft.quoted else ""
        self.query_one("#editor-anchor", _AnchorLabel).update(f"{location}{quoted}")

    def _close_editor(self) -> None:
        self._draft = None
        self.query_one("#editor", Vertical).styles.display = "none"
        self.query_one("#editor-text", Input).value = ""
        self.query_one("#diff-pane", ScrollableContainer).focus()

    def _valid_lines(self, draft: EditorDraft) -> list[int]:
        if self._view is None:
            return []
        side = draft.anchor.side if draft.anchor is not None else Side.NEW
        rendered = render_view(self._view, self._view_mode)
        return sorted(line_index(rendered, side))

    def _move_draft_anchor(self, delta: int) -> None:
        draft = self._draft
        if draft is None:
            return
        self._draft = move_anchor(draft, delta, self._valid_lines(draft))
        self._refresh_editor_anchor()

    def _toggle_editor_focus(self) -> None:
        if isinstance(self.focused, Input):
            self.query_one("#editor-anchor", _AnchorLabel).focus()
        else:
            self.query_one("#editor-text", Input).focus()

    def _confirm_draft(self, text: str) -> None:
        draft = self._draft
        change = self._state.change
        if draft is None or change is None:
            return
        comment = draft_to_comment(
            set_draft_text(draft, text), change, author=DEFAULT_AUTHOR
        )
        self._pending = put_pending(self._pending, comment)
        self._close_editor()
        self._status = "staged (not saved)"
        self._refresh_files()
        self._refresh_diff(preserve_scroll=True)

    def _reload_comments(self) -> None:
        change = self._state.change
        if change is None or self._store is None:
            return
        try:
            self._comments = load_comments(self._store, change.id)
        except StoreError as exc:
            self._status = f"store error: {exc}"
        self._view_state = self._build_comment_view()
        self._refresh_files()
        self._refresh_diff(preserve_scroll=True)

    def action_cancel(self) -> None:
        if self._draft is not None:
            self._close_editor()
            self._status = "draft cancelled"
            self._refresh_status()
            return
        if self._range_mode:
            self._range_mode = False
            self._selection = select_line(
                self._selection, self._selected_line, self._side_at(self._selected_line)
            )
            self._status = "range off"
            self._refresh_status()
            self._paint(layout=False)

    def on_resize(self, event: Resize) -> None:
        self._paint()
        self._paint_markers()

    def on_key(self, event: Key) -> None:
        if self._draft is None:
            return
        if event.key == "escape":
            self.action_cancel()
            event.stop()
        elif event.key == "tab":
            self._toggle_editor_focus()
            event.stop()
        elif event.key in ("j", "k") and not isinstance(self.focused, Input):
            self._move_draft_anchor(1 if event.key == "j" else -1)
            event.stop()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "editor-text":
            self._confirm_draft(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "files-button":
            self.action_focus_files()
        elif event.button.id == "prev-version":
            self._select_version(-1)
        elif event.button.id == "next-version":
            self._select_version(+1)
        elif event.button.id == "help-button":
            self.action_show_help()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if (
            event.list_view.id == "files"
            and event.list_view.index is not None
            and event.list_view.index != self._state.selected
        ):
            self._set_index(event.list_view.index)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self.query_one("#diff-pane", ScrollableContainer).focus()

    def on_click(self, event: Click) -> None:
        pane = self.query_one("#diff-pane", ScrollableContainer)
        region = pane.content_region
        if not region.contains(event.screen_x, event.screen_y):
            return
        if self._rendered is None or not self._rendered.lines:
            return
        row = int(event.screen_y - region.y + pane.scroll_offset.y)
        if not 0 <= row < len(self._row_to_line):
            return
        target = self._row_to_line[row]
        if target is None or target == self._selected_line:
            return
        self._selected_line = target
        self._sync_selection()
        self._paint(layout=False)

    def on_text_selected(self, event: TextSelected) -> None:
        text = self.screen.get_selected_text()
        if text:
            self.copy_to_clipboard(text)


def run_tui(root: Path) -> int:
    store = create_store(root)
    state = load_shell_state(root, store=store)
    AgentdiffApp(state, store).run()
    return 0
