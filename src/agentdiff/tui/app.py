from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from rich.style import Style
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.events import Click, TextSelected
from textual.widgets import Footer, Label, ListItem, ListView, Static

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
    make_diff_view,
    next_hunk,
    prev_hunk,
    render_view,
)
from agentdiff.tui.session import load_shell_state
from agentdiff.tui.state import (
    ShellState,
    format_file,
    format_header,
    select_file,
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


class AgentdiffApp(App[None]):
    CSS = """
    #header {
        dock: top;
        height: 1;
    }
    #body {
        height: 1fr;
    }
    #files {
        width: 24%;
        border: round #303030;
    }
    #files:focus {
        border: round #4ec9b0;
    }
    #diff-column {
        width: 1fr;
    }
    #change-indicator {
        height: 1;
        color: #9cdcfe;
    }
    #diff-pane {
        height: 1fr;
        border: round #303030;
    }
    #diff-pane:focus {
        border: round #4ec9b0;
    }
    #diff {
        width: auto;
        text-wrap: nowrap;
    }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit", show=False),
        Binding("j", "cursor_down", "Down"),
        Binding("k", "cursor_up", "Up"),
        Binding("tab", "toggle_focus", "Switch focus"),
        Binding("n", "next_change", "Next change"),
        Binding("p", "prev_change", "Prev change"),
        Binding("]", "expand_down", "Expand down"),
        Binding("+", "expand_down", "Expand down", show=False),
        Binding("=", "expand_down", "Expand down", show=False),
        Binding("[", "expand_up", "Expand up"),
        Binding("e", "expand_all", "Expand all"),
    ]

    def __init__(self, state: ShellState) -> None:
        super().__init__()
        self._state = state
        self._view_mode = ViewMode.UNIFIED
        self._view = self._build_view(state.selected)
        self._selected_line = 0
        self._rendered: RenderedDiff | None = None
        self._base_text: Text | None = None
        self._line_ranges: list[tuple[int, int]] = []

    def _build_view(self, index: int) -> DiffView | None:
        change = self._state.change
        if change is None or not 0 <= index < len(change.files):
            return None
        entry = self._state.files[index]
        content = (
            self._state.contents[index] if index < len(self._state.contents) else None
        )
        return make_diff_view(
            change.files[index], header=format_file(entry), content=content
        )

    def compose(self) -> ComposeResult:
        yield Static(format_header(self._state), id="header")
        with Horizontal(id="body"):
            with ListView(id="files"):
                for entry in self._state.files:
                    yield ListItem(Label(format_file(entry)))
            with Vertical(id="diff-column"):
                yield Static("", id="change-indicator")
                with ScrollableContainer(id="diff-pane"):
                    yield Static("", id="diff")
        yield Footer()

    def on_mount(self) -> None:
        if self._state.files:
            self.query_one("#files", ListView).focus()
        self._refresh_diff(focus_hunk=True)

    def _set_index(self, index: int) -> None:
        self._state = select_file(self._state, index - self._state.selected)
        self._view = self._build_view(self._state.selected)
        self._selected_line = 0
        self._refresh_diff(focus_hunk=True)

    def _refresh_diff(self, *, focus_hunk: bool = False) -> None:
        diff = self.query_one("#diff", Static)
        indicator = self.query_one("#change-indicator", Static)
        if self._view is None:
            self._rendered = None
            self._base_text = None
            self._line_ranges = []
            diff.update(self._state.message or "")
            indicator.update("")
            return
        rendered = render_view(self._view, self._view_mode)
        self._rendered = rendered
        self._base_text = self._to_text(rendered)
        if focus_hunk and rendered.hunk_starts:
            index = min(self._view.hunk_index, len(rendered.hunk_starts) - 1)
            self._selected_line = rendered.hunk_starts[index]
        self._selected_line = _clamp(self._selected_line, len(rendered.lines))
        self._paint()
        count = len(self._view.file.hunks)
        indicator.update(
            f"change {self._view.hunk_index + 1} of {count}" if count else ""
        )
        self._scroll_to_hunk(rendered)

    def _paint(self, *, layout: bool = True) -> None:
        if self._base_text is None:
            return
        text = self._base_text.copy()
        if 0 <= self._selected_line < len(self._line_ranges):
            start, end = self._line_ranges[self._selected_line]
            text.stylize(self._selection_style(), start, end)
        self.query_one("#diff", Static).update(text, layout=layout)

    def _selection_style(self) -> Style:
        if self._rendered is not None and self._selected_line < len(
            self._rendered.lines
        ):
            line = self._rendered.lines[self._selected_line]
            for column in line.columns:
                if column.kind is CellKind.ADD:
                    return _SELECTED_ADD_STYLE
                if column.kind is CellKind.DEL:
                    return _SELECTED_DEL_STYLE
        return _SELECTED_LINE_STYLE

    def _move_line(self, delta: int) -> None:
        if self._rendered is None or not self._rendered.lines:
            return
        target = _clamp(self._selected_line + delta, len(self._rendered.lines))
        if target == self._selected_line:
            return
        self._selected_line = target
        self._paint(layout=False)
        self._ensure_line_visible()

    def _ensure_line_visible(self) -> None:
        pane = self.query_one("#diff-pane", ScrollableContainer)
        height = pane.scrollable_content_region.height
        if height <= 0:
            return
        offset = int(pane.scroll_offset.y)
        if self._selected_line < offset:
            pane.scroll_to(y=self._selected_line, animate=False)
        elif self._selected_line >= offset + height:
            pane.scroll_to(y=self._selected_line - height + 1, animate=False)

    def _diff_focused(self) -> bool:
        pane = self.query_one("#diff-pane", ScrollableContainer)
        focused = self.focused
        return focused is not None and (focused is pane or pane in focused.ancestors)

    def _scroll_to_hunk(self, rendered: RenderedDiff) -> None:
        if self._view is None or not rendered.hunk_starts:
            return
        index = min(self._view.hunk_index, len(rendered.hunk_starts) - 1)
        pane = self.query_one("#diff-pane", ScrollableContainer)
        pane.scroll_to(y=rendered.hunk_starts[index], animate=False)

    def _to_text(self, rendered: RenderedDiff) -> Text:
        text = Text()
        ranges: list[tuple[int, int]] = []
        for index, line in enumerate(rendered.lines):
            if index:
                text.append("\n")
            start = len(text)
            self._append_line(text, line)
            ranges.append((start, len(text)))
        self._line_ranges = ranges
        return text

    def _append_line(self, text: Text, line: DisplayLine) -> None:
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

    def action_next_change(self) -> None:
        if self._view is None:
            return
        view = next_hunk(self._view)
        if view is not self._view:
            self._view = view
            self._refresh_diff(focus_hunk=True)

    def action_prev_change(self) -> None:
        if self._view is None:
            return
        view = prev_hunk(self._view)
        if view is not self._view:
            self._view = view
            self._refresh_diff(focus_hunk=True)

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
        if self._view is None:
            return
        view = expand_all_view(self._view)
        if view is not self._view:
            self._view = view
            self._refresh_diff()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.index is not None:
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
        line = int(event.screen_y - region.y + pane.scroll_offset.y)
        target = _clamp(line, len(self._rendered.lines))
        if target == self._selected_line:
            return
        self._selected_line = target
        self._paint(layout=False)

    def on_text_selected(self, event: TextSelected) -> None:
        text = self.screen.get_selected_text()
        if text:
            self.copy_to_clipboard(text)


def run_tui(root: Path) -> int:
    state = load_shell_state(root)
    AgentdiffApp(state).run()
    return 0
