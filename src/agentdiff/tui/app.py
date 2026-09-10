from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, VerticalScroll
from textual.events import TextSelected
from textual.widgets import Footer, Label, ListItem, ListView, Static

from agentdiff.tui.session import load_shell_state
from agentdiff.tui.state import ShellState, format_file, format_header, select_file


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
    }
    #diff-pane {
        width: 1fr;
    }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit", show=False),
        Binding("j", "cursor_down", "Down"),
        Binding("k", "cursor_up", "Up"),
    ]

    def __init__(self, state: ShellState) -> None:
        super().__init__()
        self._state = state

    def compose(self) -> ComposeResult:
        yield Static(format_header(self._state), id="header")
        with Horizontal(id="body"):
            with ListView(id="files"):
                for entry in self._state.files:
                    yield ListItem(Label(format_file(entry)))
            with VerticalScroll(id="diff-pane"):
                yield Static(self._state.current_preview, id="diff")
        yield Footer()

    def on_mount(self) -> None:
        if self._state.files:
            self.query_one("#files", ListView).focus()

    def _set_index(self, index: int) -> None:
        self._state = select_file(self._state, index - self._state.selected)
        self.query_one("#diff", Static).update(self._state.current_preview)

    def action_cursor_down(self) -> None:
        self.query_one("#files", ListView).action_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one("#files", ListView).action_cursor_up()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.index is not None:
            self._set_index(event.list_view.index)

    def on_text_selected(self, event: TextSelected) -> None:
        text = self.screen.get_selected_text()
        if text:
            self.copy_to_clipboard(text)


def run_tui(root: Path) -> int:
    state = load_shell_state(root)
    AgentdiffApp(state).run()
    return 0
