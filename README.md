# agentdiff

Leave inline comments on a diff in a terminal UI, then hand those comments to
an AI coding agent through a stable JSON/CLI interface. It's a generalization of
Gerrit's inline diff comments: instead of being locked to a review platform, the
human→comment authoring loop and the harness→consumption loop share one
frontend-agnostic core.

```
Human ──► TUI ──► core engine (git ingestion) ──► CLI / JSON / MCP ──► any agent harness
```

agentdiff is **not** a code-review platform and **not** an agent. It records
what a human wants changed, anchored to exact lines, and exports it.

## Install

Requires Python ≥ 3.10 and `git`.

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

This installs the `agentdiff` command into the venv. Either activate it
(`source .venv/bin/activate`) or call `.venv/bin/agentdiff` directly.

## Quickstart

agentdiff reviews **committed** changes — the diff of `HEAD~1..HEAD` (the latest
commit against its parent). Commit your work first.

```sh
# 1. Review the current commit in the TUI and leave comments
.venv/bin/agentdiff

# 2. Confirm your staged comments (see "Comments are staged" below)
#    then quit.

# 3. Hand the comments to an agent as the JSON contract
.venv/bin/agentdiff export --format json
```

## Concepts

- **Change** — one *review*: a branch's committed range (`base..HEAD`, default
  `HEAD~1..HEAD`). Its id is stable, derived from `(branch, base_revision)`, so
  amending the commit does **not** create a new change.
- **Version** — one *patchset* of a change. Each amend appends a version (a new
  head SHA + diff snapshot). Older versions are readable history.
- **Comment** — anchored to a `(file, side, line range)` on a specific
  **version**, and belongs to the change. Comments form **reply chains**
  (`in_reply_to`).
- **Lifecycle** — `ACTIVE → RESOLVED → CLOSED`. Amending resolves the previous
  version's comments; `CLOSED` comments are retained but hidden by default.

The store lives in `.agentdiff/` (one JSONL file per change) and is
**gitignored** — comments never ship with your code.

## TUI

Bare `agentdiff` (on a TTY) opens the review UI. Main keys:

| Key | Action |
|---|---|
| `j` / `k` | move the line cursor |
| `v` | toggle range selection |
| `c` | comment on the selected line/range |
| `r` | reply to the selected comment |
| `s` | resolve the selected comment (appends a `RESOLVED` reply) |
| `x` | close the selected comment |
| `C` | **confirm comments** — write all staged comments to the store |
| `d` | remove a staged comment |
| `n` / `p` | next / previous change (hunk) |
| `[` / `]` / `e` | expand context / expand all |
| `h` / `l` | previous / next **version** (history; read-only) |
| `tab` | switch focus (files ↔ diff) |
| `q` | quit |

**Comments are staged, not written immediately.** Confirming a comment (`c` →
type → confirm) puts it in a pending buffer; nothing is persisted until you
press **`C` (Confirm comments)**, which flushes them all at once. An agent sees
nothing until then.

## CLI

The CLI is read-only for discovery/export and also provides comment actions, so
a harness without MCP can script the whole loop.

```
agentdiff changes                 # list stored changes (with versions + comment counts)
agentdiff changes --revision SHA  # find the change whose versions include this commit
agentdiff list --change ID        # list a change's comments
agentdiff list --change ID --threads                    # group into reply threads
agentdiff list --change ID --thread-state resolved      # only resolved threads
agentdiff export --change ID      # export comments (markdown default, or --format json)
agentdiff add ...                 # author a comment or reply
agentdiff resolve ID              # mark addressed (appends a RESOLVED reply)
agentdiff reopen ID               # reopen as a reply on the current version
agentdiff close ID                # human verdict — sets CLOSED (hidden by default)
```

All commands accept `--root PATH` (the repo containing `.agentdiff/`, default
cwd). `list`, `export`, and `changes` hide `CLOSED` comments unless you pass
`--include-closed`.

`list --threads` prints each reply thread with a derived status marker
(`[open]` / `[resolved]` / `[closed]`) and its replies indented. `--thread-state`
shows only threads whose derived status matches (the whole thread) and implies
`--threads`. Note the difference: `--state` filters an individual comment's
**own** state, while `--thread-state` filters by the **thread's derived** status.
Resolving appends a `RESOLVED` reply and leaves the root `ACTIVE`, so a resolved
thread's root is not itself `RESOLVED` — use `--thread-state resolved`.

### Finding a change from a commit

Change ids are stable hashes derived from `(branch, base_revision)`, so they
aren't human-guessable. Given a commit SHA, look up its change:

```sh
agentdiff changes --revision a0373ca2        # also: --commit a0373ca2
# chg-1ba1823f4da65ef2
```

Then feed it to `--change`:

```sh
agentdiff export --change "$(agentdiff changes --revision a0373ca2)" --format json
```

### Examples

```sh
# Author a range comment
agentdiff add src/foo.py --lines 300-364 --message "Extract this into a helper"

# Reply to an existing comment
agentdiff add src/foo.py --in-reply-to c-abc123 --message "Done in the new helper"

# Resolve (agent) and later close (human)
agentdiff resolve c-abc123
agentdiff close c-abc123
```

## JSON export (the agent contract)

`agentdiff export --format json` emits a versioned document:

```json
{
  "schema_version": "1.0.0",
  "change": {
    "id": "chg-1ba1823f4da65ef2",
    "branch": "feat/x",
    "base_revision": "7f5faef0...",
    "current_revision": "a0373ca2...",
    "versions": ["a0373ca2..."],
    "approval": null,
    "files": [{ "path": "src/foo.py", "additions": 12, "deletions": 4, "old_path": null }]
  },
  "comments": [
    {
      "id": "c-1f5caf5f...",
      "revision": "a0373ca2...",
      "file": "src/foo.py",
      "side": "NEW",
      "lines": [300, 364],
      "text": "Extract this into a helper",
      "author": "reviewer",
      "in_reply_to": null,
      "state": "ACTIVE",
      "drifted": false,
      "created_at": "2026-09-12T00:24:00Z"
    }
  ],
  "threads": [
    { "root": "c-1f5caf5f...", "state": "open", "comments": ["c-1f5caf5f..."] }
  ]
}
```

- `lines` is `[start, end]`, 1-based inclusive (`null` = file-level comment).
- `state` is `ACTIVE`, `RESOLVED`, or `CLOSED`; `CLOSED` is omitted by default.
- `drifted: true` means the comment's anchor could not be found in the current
  version (it renders as a file-level note).
- `threads` gives each reply chain's derived status explicitly — `state` is
  `open`/`resolved`/`closed` (the latest member's state), so consumers don't have
  to reconstruct it from `in_reply_to` ordering. Resolving appends a `RESOLVED`
  reply, so a resolved thread's root stays `ACTIVE`; read the thread `state`.
- The schema is versioned; see `ARCHITECTURE.md §7` for the change policy.

## For agent harnesses

An agent's job is usually one command:

```sh
agentdiff export --format json
```

That returns the line-anchored comments for the current change. Work from the
top-level **`threads`** array: address the comments in each thread whose
`state` is `open` (`file` + `lines` + `side`), then `resolve` it. Don't rely on
a comment's own `state` — resolving appends a `RESOLVED` reply and leaves the
root `ACTIVE`, so a thread's `state` is what tells you whether it's done. From
the shell, `agentdiff list --thread-state open` gives the same view. The human
reviews and `close`s. A live MCP server (`agentdiff serve-mcp`) is on the
roadmap.

## Development

```sh
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

- `ARCHITECTURE.md` — the source of truth: structure, data model, contracts,
  decisions, and roadmap.
- `AGENTS.md` — how agents work in this repo.

## Status

Working: diff ingestion (committed ranges), the versioned change/comment model
with reply threads, the TUI (viewer + commenting + version history), and the CLI
(discovery, export, authoring, resolve/reopen/close, thread-aware listing and
thread status in the JSON export).

Roadmap: version↔version diff view, side-by-side view, MCP server, agent-facing
docs, optional GUI.
