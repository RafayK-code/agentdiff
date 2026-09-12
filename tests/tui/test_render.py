from __future__ import annotations

from tests.diff.conftest import load_fixture

from agentdiff.diff.parse import parse_unified_diff
from agentdiff.model.types import FileDiff, Hunk, Line, Side
from agentdiff.tui.render import (
    CellKind,
    RowKind,
    ViewMode,
    build_rows,
    compute_context_gaps,
    expand_all_view,
    expand_view,
    intra_line_spans,
    line_index,
    line_number,
    make_diff_view,
    next_hunk,
    prev_hunk,
    render_view,
)
from agentdiff.tui.state import FileContent, format_file, summarize_file


def _file(*hunks: Hunk) -> FileDiff:
    return FileDiff(path="f.txt", hunks=list(hunks))


def _context_file() -> FileDiff:
    hunk0 = Hunk(
        old_start=5,
        old_count=3,
        new_start=5,
        new_count=3,
        lines=[
            Line(kind="ctx", old_no=5, new_no=5, text="a"),
            Line(kind="del", old_no=6, new_no=None, text="b"),
            Line(kind="add", old_no=None, new_no=6, text="c"),
            Line(kind="ctx", old_no=7, new_no=7, text="d"),
        ],
    )
    hunk1 = Hunk(
        old_start=20,
        old_count=1,
        new_start=20,
        new_count=2,
        lines=[
            Line(kind="del", old_no=20, new_no=None, text="x"),
            Line(kind="add", old_no=None, new_no=20, text="y"),
            Line(kind="add", old_no=None, new_no=21, text="z"),
        ],
    )
    return _file(hunk0, hunk1)


def _gaps(file: FileDiff, total_lines: int | None) -> list[tuple]:
    gaps = compute_context_gaps(file, total_lines=total_lines, content_side=Side.NEW)
    return [
        (g.index, g.old_start, g.old_end, g.new_start, g.new_end, g.count) for g in gaps
    ]


def test_context_gaps_cover_leading_between_trailing() -> None:
    file = _context_file()

    assert _gaps(file, 30) == [
        (0, 1, 4, 1, 4, 4),
        (1, 8, 19, 8, 19, 12),
        (2, 21, 29, 22, 30, 9),
    ]
    assert _gaps(file, None) == [
        (0, 1, 4, 1, 4, 4),
        (1, 8, 19, 8, 19, 12),
    ]


def test_intra_line_spans_isolate_the_changed_word() -> None:
    del_spans, add_spans = intra_line_spans("the quick brown fox", "the quick red fox")

    assert [(s.start, s.end, s.kind) for s in del_spans] == [(10, 15, "del")]
    assert [(s.start, s.end, s.kind) for s in add_spans] == [(10, 13, "add")]
    assert intra_line_spans("same text", "same text") == ((), ())


def test_build_rows_pairs_del_add_and_layout_emits_unified_gutters() -> None:
    file = parse_unified_diff(load_fixture("basic.patch")).files[0]
    view = make_diff_view(
        file,
        header=format_file(summarize_file(file)),
        content=FileContent(side=Side.NEW, lines=("ctx1", "added", "ctx2")),
    )

    rows = build_rows(view)
    assert [row.kind for row in rows] == [
        RowKind.FILE_HEADER,
        RowKind.HUNK_HEADER,
        RowKind.CONTEXT,
        RowKind.CHANGE,
        RowKind.CONTEXT,
    ]
    change = rows[3]
    assert change.old is not None
    assert (change.old.old_no, change.old.text) == (2, "removed")
    assert change.new is not None
    assert (change.new.new_no, change.new.text) == (2, "added")

    rendered = render_view(view, mode=ViewMode.UNIFIED)
    assert rendered.hunk_starts == (1,)
    header, hunk, ctx1, removed, added, ctx2 = rendered.lines
    assert header.kind is RowKind.FILE_HEADER
    assert header.text == "[modified] src/foo.py (+1 -1)"
    assert hunk.kind is RowKind.HUNK_HEADER
    assert (hunk.text, hunk.hunk_index) == ("@@ -1,3 +1,3 @@", 0)
    assert (ctx1.columns[0].gutters, ctx1.columns[0].text) == ((1, 1), "ctx1")
    assert (
        removed.columns[0].kind,
        removed.columns[0].gutters,
        removed.columns[0].text,
    ) == (CellKind.DEL, (2, None), "removed")
    assert (
        added.columns[0].kind,
        added.columns[0].gutters,
        added.columns[0].text,
    ) == (CellKind.ADD, (None, 2), "added")
    assert (ctx2.columns[0].gutters, ctx2.columns[0].text) == ((3, 3), "ctx2")


def test_line_index_and_line_number_map_unified_coordinates() -> None:
    file = parse_unified_diff(load_fixture("basic.patch")).files[0]
    rendered = render_view(
        make_diff_view(
            file,
            header="[modified] src/foo.py",
            content=FileContent(side=Side.NEW, lines=("ctx1", "added", "ctx2")),
        )
    )

    assert line_index(rendered, Side.NEW) == {1: 2, 2: 4, 3: 5}
    assert line_index(rendered, Side.OLD) == {1: 2, 2: 3, 3: 5}
    assert line_number(rendered.lines[2], Side.NEW) == 1
    assert line_number(rendered.lines[2], Side.OLD) == 1
    assert line_number(rendered.lines[3], Side.NEW) is None
    assert line_number(rendered.lines[3], Side.OLD) == 2
    assert line_number(rendered.lines[4], Side.NEW) == 2
    assert line_number(rendered.lines[4], Side.OLD) is None
    assert line_number(rendered.lines[0], Side.NEW) is None
    assert line_number(rendered.lines[1], Side.NEW) is None


def test_binary_and_no_content_files_render_a_note() -> None:
    binary_file = parse_unified_diff(load_fixture("binary.patch")).files[0]
    mode_file = parse_unified_diff(load_fixture("mode_only.patch")).files[0]

    binary = render_view(
        make_diff_view(binary_file, header=format_file(summarize_file(binary_file)))
    )
    mode = render_view(
        make_diff_view(mode_file, header=format_file(summarize_file(mode_file)))
    )

    assert [line.kind for line in binary.lines] == [
        RowKind.FILE_HEADER,
        RowKind.NOTE,
    ]
    assert binary.lines[1].text == "(binary file)"
    assert [line.kind for line in mode.lines] == [
        RowKind.FILE_HEADER,
        RowKind.NOTE,
    ]
    assert mode.lines[1].text == "(no content changes)"


def test_hunk_navigation_clamps_without_wrapping() -> None:
    file = parse_unified_diff(load_fixture("multiple_hunks.patch")).files[0]
    view = make_diff_view(file, header="x")

    assert prev_hunk(view).hunk_index == 0
    assert next_hunk(view).hunk_index == 1
    assert next_hunk(next_hunk(view)).hunk_index == 1

    empty_file = parse_unified_diff(load_fixture("mode_only.patch")).files[0]
    empty = make_diff_view(empty_file, header="x")
    assert prev_hunk(empty).hunk_index == 0
    assert next_hunk(empty).hunk_index == 0


def test_expand_view_grows_adjacent_gap_and_expand_all_reveals_everything() -> None:
    file = _file(
        Hunk(
            old_start=3,
            old_count=1,
            new_start=3,
            new_count=1,
            lines=[
                Line(kind="del", old_no=3, new_no=None, text="old3"),
                Line(kind="add", old_no=None, new_no=3, text="new3"),
            ],
        )
    )
    content = FileContent(
        side=Side.NEW, lines=("l1", "l2", "new3", "l4", "l5", "l6", "l7")
    )
    view = make_diff_view(file, header="x", content=content)
    assert [gap.count for gap in view.gaps] == [2, 4]

    down2 = expand_view(view, direction="down", amount=2)
    assert (down2.expansion[0].top, down2.expansion[0].bottom) == (0, 0)
    assert (down2.expansion[1].top, down2.expansion[1].bottom) == (2, 0)

    down10 = expand_view(down2, direction="down", amount=10)
    assert (down10.expansion[1].top, down10.expansion[1].bottom) == (4, 0)

    up1 = expand_view(view, direction="up", amount=1)
    assert (up1.expansion[0].top, up1.expansion[0].bottom) == (0, 1)

    initial = render_view(view)
    assert all(line.kind is not RowKind.SKIP for line in initial.lines)
    initial_contexts = [
        (line.columns[0].gutters[1], line.columns[0].text)
        for line in initial.lines
        if line.kind is RowKind.CONTEXT
    ]
    assert initial_contexts == [
        (1, "l1"),
        (2, "l2"),
        (4, "l4"),
        (5, "l5"),
        (6, "l6"),
        (7, "l7"),
    ]

    full = render_view(expand_all_view(view))
    assert all(line.kind is not RowKind.SKIP for line in full.lines)
    contexts = [line for line in full.lines if line.kind is RowKind.CONTEXT]
    assert [
        (line.columns[0].gutters[1], line.columns[0].text) for line in contexts
    ] == [
        (1, "l1"),
        (2, "l2"),
        (4, "l4"),
        (5, "l5"),
        (6, "l6"),
        (7, "l7"),
    ]
    assert any(line.kind is RowKind.HUNK_HEADER for line in full.lines)


def test_large_gap_collapses_and_expands() -> None:
    file = _file(
        Hunk(
            old_start=15,
            old_count=1,
            new_start=15,
            new_count=1,
            lines=[
                Line(kind="del", old_no=15, new_no=None, text="old"),
                Line(kind="add", old_no=None, new_no=15, text="new"),
            ],
        )
    )
    content = FileContent(side=Side.NEW, lines=tuple(f"l{i}" for i in range(1, 21)))
    view = make_diff_view(file, header="x", content=content)
    assert [gap.count for gap in view.gaps] == [14, 5]

    initial = render_view(view)
    skip_texts = [line.text for line in initial.lines if line.kind is RowKind.SKIP]
    assert skip_texts == ["\u22ef 14 unchanged lines"]
    revealed = [
        line.columns[0].text for line in initial.lines if line.kind is RowKind.CONTEXT
    ]
    assert revealed == [f"l{i}" for i in range(16, 21)]

    up = render_view(expand_view(view, direction="up", amount=10))
    skip_texts = [line.text for line in up.lines if line.kind is RowKind.SKIP]
    assert skip_texts == ["\u22ef 4 unchanged lines"]

    full = render_view(expand_all_view(view))
    assert all(line.kind is not RowKind.SKIP for line in full.lines)
    revealed = [
        line.columns[0].text for line in full.lines if line.kind is RowKind.CONTEXT
    ]
    assert revealed == [f"l{i}" for i in range(1, 15)] + [
        f"l{i}" for i in range(16, 21)
    ]
