from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import MarkdownViewer, Static

from agentdiff.guides import TUI_GUIDE, read_guide


class HelpScreen(ModalScreen[None]):
    """Scrollable overlay showing the packaged TUI guide (R3)."""

    CSS = """
    HelpScreen {
        align: center middle;
    }
    HelpScreen > #help-body {
        width: 90%;
        height: 90%;
        border: round #4ec9b0;
        background: #1e1e1e;
    }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "dismiss", "Close"),
        Binding("?", "dismiss", "Close", show=False),
        Binding("q", "dismiss", "Close", show=False),
    ]

    def compose(self) -> ComposeResult:
        try:
            guide = read_guide(TUI_GUIDE)
        except FileNotFoundError:
            yield Static("TUI guide unavailable in this install.", id="help-body")
            return
        yield MarkdownViewer(guide, show_table_of_contents=False, id="help-body")

    def on_mount(self) -> None:
        try:
            self.query_one(MarkdownViewer).focus()  # arrow/pgup/pgdn scroll
        except NoMatches:
            pass

    def action_dismiss(self) -> None:
        self.dismiss(None)
