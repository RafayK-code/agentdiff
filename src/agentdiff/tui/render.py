from __future__ import annotations

import difflib
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import Enum
from typing import Literal

from agentdiff.model.types import FileDiff, Hunk, Line, Side
from agentdiff.tui.state import FileContent

CONTEXT_STEP: int = 10

_TOKEN_RE = re.compile(r"\w+|\s+|[^\w\s]")


class CellKind(str, Enum):
    CTX = "ctx"
    ADD = "add"
    DEL = "del"


class RowKind(str, Enum):
    FILE_HEADER = "file_header"
    HUNK_HEADER = "hunk_header"
    CONTEXT = "context"
    CHANGE = "change"
    SKIP = "skip"
    NOTE = "note"
    COMMENT = "comment"


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    kind: Literal["add", "del"]


@dataclass(frozen=True)
class Cell:
    """One side's content for a row. CONTEXT cells carry both numbers."""

    kind: CellKind
    old_no: int | None
    new_no: int | None
    text: str
    spans: tuple[Span, ...] = ()


@dataclass(frozen=True)
class DiffRow:
    """A logical diff row, independent of layout.

    ``old``/``new`` are both set for CONTEXT, one of them set for an unpaired
    CHANGE, both for a paired CHANGE.
    """

    kind: RowKind
    old: Cell | None = None
    new: Cell | None = None
    text: str = ""
    hunk_index: int | None = None


class ViewMode(str, Enum):
    UNIFIED = "unified"
    SIDE_BY_SIDE = "side_by_side"


@dataclass(frozen=True)
class Column:
    kind: CellKind
    gutters: tuple[int | None, ...]
    text: str
    spans: tuple[Span, ...] = ()


@dataclass(frozen=True)
class DisplayLine:
    kind: RowKind
    columns: tuple[Column, ...] = ()
    text: str = ""
    hunk_index: int | None = None


@dataclass(frozen=True)
class RenderedDiff:
    lines: tuple[DisplayLine, ...]
    hunk_starts: tuple[int, ...]


@dataclass(frozen=True)
class ContextGap:
    index: int
    old_start: int
    old_end: int
    new_start: int
    new_end: int
    count: int


@dataclass(frozen=True)
class GapExpansion:
    top: int = 0
    bottom: int = 0


@dataclass(frozen=True)
class DiffView:
    file: FileDiff
    header: str
    content: FileContent | None
    gaps: tuple[ContextGap, ...]
    expansion: tuple[GapExpansion, ...]
    hunk_index: int = 0


def _merge_spans(spans: list[Span]) -> tuple[Span, ...]:
    if not spans:
        return ()
    ordered = sorted(spans, key=lambda span: span.start)
    merged = [ordered[0]]
    for span in ordered[1:]:
        last = merged[-1]
        if span.start <= last.end:
            merged[-1] = Span(last.start, max(last.end, span.end), last.kind)
        else:
            merged.append(span)
    return tuple(merged)


def _token_offsets(tokens: Sequence[str]) -> list[tuple[int, int]]:
    offsets: list[tuple[int, int]] = []
    pos = 0
    for token in tokens:
        offsets.append((pos, pos + len(token)))
        pos += len(token)
    return offsets


def intra_line_spans(
    old_text: str, new_text: str
) -> tuple[tuple[Span, ...], tuple[Span, ...]]:
    """Word-level diff of two lines as (del_spans, add_spans). Pure. (R2)"""
    if old_text == new_text:
        return ((), ())
    old_tokens = _TOKEN_RE.findall(old_text)
    new_tokens = _TOKEN_RE.findall(new_text)
    old_offsets = _token_offsets(old_tokens)
    new_offsets = _token_offsets(new_tokens)
    matcher = difflib.SequenceMatcher(a=old_tokens, b=new_tokens, autojunk=False)
    del_spans: list[Span] = []
    add_spans: list[Span] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "delete") and i2 > i1:
            del_spans.append(Span(old_offsets[i1][0], old_offsets[i2 - 1][1], "del"))
        if tag in ("replace", "insert") and j2 > j1:
            add_spans.append(Span(new_offsets[j1][0], new_offsets[j2 - 1][1], "add"))
    return (_merge_spans(del_spans), _merge_spans(add_spans))


def compute_context_gaps(
    file: FileDiff, *, total_lines: int | None, content_side: Side
) -> tuple[ContextGap, ...]:
    """Unchanged line ranges around/between hunks. Pure. (R3)"""
    if not file.hunks:
        return ()
    net = sum(hunk.new_count for hunk in file.hunks) - sum(
        hunk.old_count for hunk in file.hunks
    )
    if total_lines is None:
        total_old: int | None = None
        total_new: int | None = None
    elif content_side is Side.NEW:
        total_new = total_lines
        total_old = total_lines - net
    else:
        total_old = total_lines
        total_new = total_lines + net

    boundaries: list[tuple[int, int, int, int]] = []
    first = file.hunks[0]
    boundaries.append((1, first.old_start - 1, 1, first.new_start - 1))
    for prev, nxt in zip(file.hunks, file.hunks[1:], strict=False):
        old_end = prev.old_start + prev.old_count - 1
        new_end = prev.new_start + prev.new_count - 1
        boundaries.append(
            (old_end + 1, nxt.old_start - 1, new_end + 1, nxt.new_start - 1)
        )
    if total_old is not None and total_new is not None:
        last = file.hunks[-1]
        old_end = last.old_start + last.old_count - 1
        new_end = last.new_start + last.new_count - 1
        boundaries.append((old_end + 1, total_old, new_end + 1, total_new))

    gaps: list[ContextGap] = []
    for old_start, old_end, new_start, new_end in boundaries:
        count = max(0, old_end - old_start + 1)
        gaps.append(
            ContextGap(
                index=len(gaps),
                old_start=old_start,
                old_end=old_end,
                new_start=new_start,
                new_end=new_end,
                count=count,
            )
        )
    return tuple(gaps)


def make_diff_view(
    file: FileDiff, *, header: str, content: FileContent | None = None
) -> DiffView:
    content_side = content.side if content is not None else Side.NEW
    total_lines = len(content.lines) if content is not None else None
    gaps = compute_context_gaps(
        file, total_lines=total_lines, content_side=content_side
    )
    expansion = tuple(GapExpansion() for _ in gaps)
    return DiffView(
        file=file,
        header=header,
        content=content,
        gaps=gaps,
        expansion=expansion,
        hunk_index=0,
    )


def _cell(kind: CellKind, line: Line, spans: tuple[Span, ...] = ()) -> Cell:
    return Cell(
        kind=kind,
        old_no=line.old_no,
        new_no=line.new_no,
        text=line.text,
        spans=spans,
    )


def _change_rows(dels: Sequence[Line], adds: Sequence[Line]) -> list[DiffRow]:
    rows: list[DiffRow] = []
    for k in range(max(len(dels), len(adds))):
        old_line = dels[k] if k < len(dels) else None
        new_line = adds[k] if k < len(adds) else None
        old_spans: tuple[Span, ...] = ()
        new_spans: tuple[Span, ...] = ()
        if old_line is not None and new_line is not None:
            old_spans, new_spans = intra_line_spans(old_line.text, new_line.text)
        rows.append(
            DiffRow(
                kind=RowKind.CHANGE,
                old=_cell(CellKind.DEL, old_line, old_spans)
                if old_line is not None
                else None,
                new=_cell(CellKind.ADD, new_line, new_spans)
                if new_line is not None
                else None,
            )
        )
    return rows


def _hunk_rows(hunk: Hunk, hunk_index: int) -> list[DiffRow]:
    rows: list[DiffRow] = [
        DiffRow(
            kind=RowKind.HUNK_HEADER,
            text=(
                f"@@ -{hunk.old_start},{hunk.old_count} "
                f"+{hunk.new_start},{hunk.new_count} @@"
            ),
            hunk_index=hunk_index,
        )
    ]
    lines = hunk.lines
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.kind == "ctx":
            cell = Cell(
                kind=CellKind.CTX,
                old_no=line.old_no,
                new_no=line.new_no,
                text=line.text,
            )
            rows.append(DiffRow(kind=RowKind.CONTEXT, old=cell, new=cell))
            i += 1
            continue
        dels: list[Line] = []
        while i < len(lines) and lines[i].kind == "del":
            dels.append(lines[i])
            i += 1
        adds: list[Line] = []
        while i < len(lines) and lines[i].kind == "add":
            adds.append(lines[i])
            i += 1
        rows.extend(_change_rows(dels, adds))
    return rows


def _line_text(view: DiffView, old_no: int, new_no: int) -> str:
    content = view.content
    if content is None:
        return ""
    number = new_no if content.side is Side.NEW else old_no
    if 1 <= number <= len(content.lines):
        return content.lines[number - 1]
    return ""


def _gap_context_row(view: DiffView, gap: ContextGap, offset: int) -> DiffRow:
    old_no = gap.old_start + offset
    new_no = gap.new_start + offset
    cell = Cell(
        kind=CellKind.CTX,
        old_no=old_no,
        new_no=new_no,
        text=_line_text(view, old_no, new_no),
    )
    return DiffRow(kind=RowKind.CONTEXT, old=cell, new=cell)


def _gap_rows(view: DiffView, gap_index: int) -> list[DiffRow]:
    if not 0 <= gap_index < len(view.gaps):
        return []
    gap = view.gaps[gap_index]
    if gap.count <= 0:
        return []
    expansion = view.expansion[gap_index]
    top = max(0, min(gap.count, expansion.top))
    bottom = max(0, min(gap.count, expansion.bottom))
    if view.content is None:
        top = bottom = 0
    elif gap.count < CONTEXT_STEP:
        top = gap.count
        bottom = 0
    rows: list[DiffRow] = []
    if top + bottom >= gap.count:
        rows.extend(_gap_context_row(view, gap, offset) for offset in range(gap.count))
        return rows
    rows.extend(_gap_context_row(view, gap, offset) for offset in range(top))
    hidden = gap.count - top - bottom
    if hidden > 0:
        rows.append(DiffRow(kind=RowKind.SKIP, text=f"\u22ef {hidden} unchanged lines"))
    rows.extend(
        _gap_context_row(view, gap, offset)
        for offset in range(gap.count - bottom, gap.count)
    )
    return rows


def build_rows(view: DiffView) -> tuple[DiffRow, ...]:
    """Semantic, mode-agnostic rows for a diff view. Pure. (R1/R6/R7/R9)"""
    file = view.file
    rows: list[DiffRow] = [DiffRow(kind=RowKind.FILE_HEADER, text=view.header)]
    if file.is_binary:
        rows.append(DiffRow(kind=RowKind.NOTE, text="(binary file)"))
        return tuple(rows)
    if not file.hunks:
        rows.append(DiffRow(kind=RowKind.NOTE, text="(no content changes)"))
        return tuple(rows)
    for index, hunk in enumerate(file.hunks):
        rows.extend(_gap_rows(view, index))
        rows.extend(_hunk_rows(hunk, index))
    rows.extend(_gap_rows(view, len(file.hunks)))
    return tuple(rows)


def layout_unified(rows: Sequence[DiffRow]) -> RenderedDiff:
    lines: list[DisplayLine] = []
    hunk_starts: list[int] = []
    for row in rows:
        if row.kind is RowKind.HUNK_HEADER:
            hunk_starts.append(len(lines))
            lines.append(
                DisplayLine(kind=row.kind, text=row.text, hunk_index=row.hunk_index)
            )
            continue
        if row.kind is RowKind.CONTEXT:
            cell = row.old
            assert cell is not None
            lines.append(
                DisplayLine(
                    kind=RowKind.CONTEXT,
                    columns=(
                        Column(
                            kind=cell.kind,
                            gutters=(cell.old_no, cell.new_no),
                            text=cell.text,
                            spans=cell.spans,
                        ),
                    ),
                )
            )
            continue
        if row.kind is RowKind.CHANGE:
            for cell in (row.old, row.new):
                if cell is None:
                    continue
                lines.append(
                    DisplayLine(
                        kind=RowKind.CHANGE,
                        columns=(
                            Column(
                                kind=cell.kind,
                                gutters=(cell.old_no, cell.new_no),
                                text=cell.text,
                                spans=cell.spans,
                            ),
                        ),
                    )
                )
            continue
        lines.append(DisplayLine(kind=row.kind, text=row.text))
    return RenderedDiff(lines=tuple(lines), hunk_starts=tuple(hunk_starts))


def layout_side_by_side(rows: Sequence[DiffRow]) -> RenderedDiff:
    raise NotImplementedError("side-by-side layout lands in slice 09")


def render_view(view: DiffView, mode: ViewMode = ViewMode.UNIFIED) -> RenderedDiff:
    rows = build_rows(view)
    if mode is ViewMode.UNIFIED:
        return layout_unified(rows)
    if mode is ViewMode.SIDE_BY_SIDE:
        return layout_side_by_side(rows)
    raise ValueError(f"unknown view mode: {mode!r}")


def next_hunk(view: DiffView) -> DiffView:
    last = len(view.file.hunks) - 1
    if last < 0:
        return view
    index = min(last, view.hunk_index + 1)
    return view if index == view.hunk_index else replace(view, hunk_index=index)


def prev_hunk(view: DiffView) -> DiffView:
    if not view.file.hunks:
        return view
    index = max(0, view.hunk_index - 1)
    return view if index == view.hunk_index else replace(view, hunk_index=index)


def expand_view(
    view: DiffView, *, direction: Literal["up", "down"], amount: int = CONTEXT_STEP
) -> DiffView:
    if direction == "down":
        gap_index = view.hunk_index + 1
        grow_top = True
    elif direction == "up":
        gap_index = view.hunk_index
        grow_top = False
    else:
        raise ValueError(f"unknown direction: {direction!r}")
    if not 0 <= gap_index < len(view.gaps):
        return view
    gap = view.gaps[gap_index]
    expansion = view.expansion[gap_index]
    if grow_top:
        new = GapExpansion(
            top=min(gap.count, expansion.top + amount), bottom=expansion.bottom
        )
    else:
        new = GapExpansion(
            top=expansion.top, bottom=min(gap.count, expansion.bottom + amount)
        )
    if new == expansion:
        return view
    updated = list(view.expansion)
    updated[gap_index] = new
    return replace(view, expansion=tuple(updated))


def expand_all_view(view: DiffView) -> DiffView:
    expansion = tuple(GapExpansion(top=gap.count) for gap in view.gaps)
    return view if expansion == view.expansion else replace(view, expansion=expansion)


def line_side(line: DisplayLine) -> Side | None:
    """Side a unified display line anchors to. (R1/R2)

    A unified ``-`` (DEL) line is the ``OLD`` side, a ``+`` (ADD) line is the
    ``NEW`` side, and a context/header/skip/note/comment row is neutral (None).
    """
    for column in line.columns:
        if column.kind is CellKind.DEL:
            return Side.OLD
        if column.kind is CellKind.ADD:
            return Side.NEW
    return None


def line_number(line: DisplayLine, side: Side) -> int | None:
    """The model line number a unified display line carries on `side`. (R4)"""
    index = 0 if side is Side.OLD else 1
    for column in line.columns:
        if index < len(column.gutters):
            number = column.gutters[index]
            if number is not None:
                return number
    return None


def line_index(rendered: RenderedDiff, side: Side) -> dict[int, int]:
    """First display-line index for each model line number on `side`. (R3/R4)"""
    result: dict[int, int] = {}
    for index, line in enumerate(rendered.lines):
        number = line_number(line, side)
        if number is not None and number not in result:
            result[number] = index
    return result
