# TUI guide

Bare `agentdiff` (on a TTY) opens the review UI. It reviews **committed**
changes — the diff of `HEAD~1..HEAD` (the latest commit against its parent) —
so commit your work first. This guide covers every key, the selection model,
staging, the colors, navigation, and the editor. The same guide is available
in-app: press `?` or click the `?` header button.

## Layout

- **Header** — `files` button, `‹` / `›` version buttons, the change label, and
  the `?` help button.
- **Files** (left) — one row per changed file, with colored thread counts.
- **Diff** (right) — the unified diff for the selected file, with a marker
  column on its right edge.
- **Meta line** — thread position (`thread N of M`) and status (`pending: N`,
  `history (read-only)`).
- **Editor** — appears at the bottom when you are authoring a comment.
- **Footer** — the active key hints.

## Keys

| Key | Action |
|---|---|
| `j` / `k` | move the line cursor (or the file list when it is focused) |
| `v` | toggle range selection |
| `c` | comment on the selected line/range |
| `F` | comment on the whole file (file-level) |
| `r` | reply to the selected comment |
| `s` | resolve the selected comment (appends a `RESOLVED` reply) |
| `x` | close the selected comment's whole thread |
| `C` | **confirm comments** — write all staged comments to the store |
| `d` | remove a staged comment |
| `n` / `p` | next / previous comment **thread** |
| `[` | expand context up |
| `]` / `+` / `=` | expand context down |
| `e` | expand all (or edit the selected staged comment) |
| `h` / `l` | previous / next **version** (history; read-only) |
| `tab` | switch focus (files ↔ diff) |
| `f` | back to the file list |
| `?` | open this guide in a scrollable overlay |
| `q` / `ctrl+c` | quit |
| `escape` | cancel the current draft / range mode |

The header's `files`, `‹`, `›`, and `?` buttons do the same as `f`, `h`, `l`,
and `?`.

## Selection

The diff cursor is a single line; `v` turns on **range mode** so `j`/`k` extend
a range instead of moving a point. A range is **side-aware**:

- Grey **context** lines are neutral and never lock the range's side.
- The first colored line locks the side — added (`+`) lines lock `NEW`, removed
  (`-`) lines lock `OLD`.
- Moving onto the opposite color is refused (the cursor holds), and opposite-
  color lines are skipped while extending.
- A neutral (context-only) range resolves to `NEW` when the comment is built.

This lets you comment on **removed (`-`) lines** as well as added/context lines:
an `OLD`-side comment anchors to the code *before* the change, so a consumer
knows what it refers to.

## Staging vs confirm

**Comments are staged, not written immediately.** Confirming a comment (`c` →
type → `Enter`) puts it in a pending buffer; nothing is persisted until you press
**`C` (Confirm comments)**, which flushes them all at once. Until then an agent
sees nothing. Staged comments are shown in the diff as pending and counted as
`draft` in the file list; `d` removes one, and `e` on a staged comment reopens
its editor.

## Colors

There are two independent color signals.

**Per-comment (the comment box and its text)** — colored by the comment's own
author, with pending/resolved overriding. A comment never changes color because
someone replied to it.

| Kind | Color |
|---|---|
| Human | red |
| Agent | blue |
| Pending (staged) | yellow, italic |
| Resolved | teal, italic |

**Thread (the scrollbar marker column and the per-file counts)** — colored by the
thread's derived conversation state:

| Thread kind | Meaning | Color |
|---|---|---|
| Awaiting agent | `open`, last reply from the human | red |
| Awaiting you | `open`, last reply from the agent | blue |
| Resolved | latest member `RESOLVED` | teal |
| Pending | tip is a staged comment | yellow |

The file list shows up to four counts per file — draft, resolved, awaiting-agent,
and awaiting-you — in the matching thread colors.

The diff itself uses the usual add/delete backgrounds, with changed tokens
highlighted more strongly; file headers, hunk headers, the focused hunk, and
skipped/notes lines have their own styles.

## Navigation

- **Threads** — `n` / `p` jump to the next / previous thread across files. The
  meta line shows `thread N of M`; the marker column shows where threads sit in
  the file.
- **Versions** — `h` / `l` move through the change's versions (history). Older
  versions are read-only: authoring is disabled and the status shows
  `history (read-only)`.
- **Files** — the left list selects a file; `f` (or the `files` button) returns
  focus to it. `tab` switches focus between the file list and the diff.

## Editor

Authoring opens the editor at the bottom with the draft's anchor and any quoted
text:

- `Enter` confirms the draft into the pending buffer.
- `escape` cancels it.
- `tab` toggles focus between the anchor label and the text input.
- With the anchor focused, `j` / `k` move the draft's anchor line.

## Help overlay

`?` (or the header's `?` button) opens this guide in a scrollable overlay.
`escape`, `?`, or `q` dismisses it. `?` is a printable character, so while the
comment editor's text input has focus it is typed into the comment instead of
opening help — the header button is the always-available affordance.
