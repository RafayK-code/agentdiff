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
| `F` | comment on the whole file (file-level) |
| `r` | reply to the selected comment |
| `s` | resolve the selected comment (appends a `RESOLVED` reply) |
| `x` | close the selected comment |
| `C` | **confirm comments** — write all staged comments to the store |
| `d` | remove a staged comment |
| `n` / `p` | next / previous comment **thread** |
| `[` / `]` / `e` | expand context / expand all |
| `h` / `l` | previous / next **version** (history; read-only) |
| `tab` | switch focus (files ↔ diff) |
| `f` | back to the file list |
| `q` | quit |

Each comment is colored by its **own author** (human vs agent), with pending and
resolved overriding — a comment never changes color because someone replied to
it. The **thread** color (awaiting you / awaiting the agent / resolved / pending)
lives on the scrollbar marker column and the per-file counts.

**Comments are staged, not written immediately.** Confirming a comment (`c` →
type → confirm) puts it in a pending buffer; nothing is persisted until you
press **`C` (Confirm comments)**, which flushes them all at once. An agent sees
nothing until then.

You can comment on **removed (`-`) lines** as well as added/context lines: the
comment anchors to the old side, so an agent knows it refers to the code *before*
the change. A `v` visual range stays on one side — grey context lines never lock
it, the first colored line fixes the side, and extending onto the other color is
refused.

## CLI

The CLI is read-only for discovery/export and also provides comment actions, so
a harness without MCP can script the whole loop.

```
agentdiff changes                 # list stored changes (with versions + comment counts)
agentdiff changes --revision SHA  # find the change whose versions include this commit
agentdiff list --change ID        # list a change's comments
agentdiff list --change ID --threads                    # group into reply threads
agentdiff list --change ID --thread-state resolved      # only resolved threads
agentdiff list --change ID --last-author human          # only human-last threads
agentdiff export --change ID      # export comments (markdown default, or --format json)
agentdiff show <comment-id>       # show one comment with the diff hunks it anchors to
agentdiff add ...                 # author a comment, or reply (--thread <root> / --in-reply-to <id>)
agentdiff resolve <thread-id>     # resolve a thread (thread-id = threads[].root)
agentdiff reopen <thread-id>      # reopen a thread as a reply on the current version
agentdiff close <thread-id>       # human verdict — close the whole thread (hidden by default)
```

All commands accept `--root PATH` (the repo containing `.agentdiff/`, default
cwd). `list`, `export`, and `changes` hide `CLOSED` comments unless you pass
`--include-closed`.

`resolve`, `reopen`, and `close` operate on a **thread**, identified by its
**root comment id** — the `root` field in the export's `threads` array. Passing
a non-root id is an error. `add` authors individual comments/replies and is the
only command that creates new comments (only on the current version). For replies,
`add --thread <root>` is thread-based: it attaches the reply to the thread's
**tip**, so you never have to name a specific comment. `--in-reply-to <comment-id>`
replies to one exact comment (rare; prefer `--thread`); the two are mutually
exclusive.

`show <comment-id>` prints one comment (naming its `side` and lines) followed by
the canonical diff hunks it anchors to — on-demand surrounding context without
bloating the JSON export. An unknown id exits 1.

`list --threads` prints each reply thread with a derived status marker
(`[open]` / `[resolved]` / `[closed]`), the last responder (`last=human` /
`last=agent`), and its replies indented. `--thread-state` shows only threads
whose derived status matches (the whole thread) and implies `--threads`.
`--last-author human|agent` filters threads by the role of the last reply (it
also implies `--threads` and is orthogonal to `--thread-state`, so the two
combine). Note the difference: `--state` filters an individual comment's
**own** state, while `--thread-state` filters by the **thread's derived** status.
Resolving appends a `RESOLVED` reply and leaves the root `ACTIVE`, so a resolved
thread's root is not itself `RESOLVED` — use `--thread-state resolved`.

The CLI authors as `AGENT` by default (it is the harness surface): `add`,
`resolve`, and `reopen` all take `--role human|agent` to override. `role` is
independent of `--author` (the free-form name).

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

# Reply to a thread (attaches to the thread's tip — pass the root id)
agentdiff add src/foo.py --thread c-root123 --message "Done in the new helper"

# Reply to one specific comment (rare; prefer --thread)
agentdiff add src/foo.py --in-reply-to c-abc123 --message "Done in the new helper"

# Resolve (agent) and later close (human) — both take the thread's root id
agentdiff resolve c-root123
agentdiff close c-root123
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
      "context": ["def process(items):", "    return items.sort()"],
      "text": "Extract this into a helper",
      "author": "reviewer",
      "role": "HUMAN",
      "in_reply_to": null,
      "state": "ACTIVE",
      "drifted": false,
      "created_at": "2026-09-12T00:24:00Z"
    }
  ],
  "threads": [
    {
      "root": "c-1f5caf5f...",
      "state": "open",
      "last_author": "HUMAN",
      "comments": ["c-1f5caf5f..."]
    }
  ]
}
```

- `lines` is `[start, end]`, 1-based inclusive (`null` = file-level comment).
- `side` is `OLD` or `NEW` (`null` = file-level): it tells a consumer whether
  the anchor is on the **removed** (old) or **added/current** (new) code.
- `context` is the comment's stored `anchor_snapshot` — the exact lines it was
  written against (`[]` = file-level). For `side: OLD` these are the **removed**
  lines (the "before"); for `side: NEW` the added/current lines. It is projected
  verbatim from the store, never recomputed. Together `side` + `lines` + `context`
  tell an agent which side, which line numbers, and which exact lines to look at.
- `role` is `HUMAN` or `AGENT`: which side authored the comment. It is set at
  authorship (the TUI is the human surface, the CLI is the harness surface) and
  is independent of the free-form `author` name.
- `state` is `ACTIVE`, `RESOLVED`, or `CLOSED`; `CLOSED` is omitted by default.
- `drifted: true` means the comment's anchor could not be found in the current
  version (it renders as a file-level note).
- `threads` gives each reply chain's derived status explicitly — `state` is
  `open`/`resolved`/`closed` (the latest member's state) and `last_author` is
  the role of the latest member — so consumers don't have to reconstruct either
  from `in_reply_to` ordering. An `open` thread whose `last_author` is `HUMAN`
  is awaiting the agent; `AGENT` is awaiting the human. Resolving appends a
  `RESOLVED` reply, so a resolved thread's root stays `ACTIVE`; read the thread
  `state`.
- The schema is versioned; see `ARCHITECTURE.md §7` for the change policy.

## For agent harnesses

An agent's job is usually one command:

```sh
agentdiff export --format json
```

That returns the line-anchored comments for the current change. Work from the
top-level **`threads`** array: address the comments in each thread whose `state`
is `open` and whose `last_author` is `HUMAN` — those are **awaiting the agent**.
An `open` thread with `last_author: AGENT` is awaiting the human. For each
awaiting thread, use `file` + `lines` + `side`; if you can address the comment,
**resolve** the thread by its `root` id (`agentdiff resolve <root>`); if you
cannot, **reply** with an explanation or a question instead of resolving — reply
by thread root so it always lands on the tip
(`agentdiff add src/foo.py --thread <root> --role agent --message "..."`).
Don't rely on a comment's own `state` — resolving appends a `RESOLVED` reply and
leaves the root `ACTIVE`, so a thread's `state` is what tells you whether it's
done. From the shell, the actionable set is the two filters combined:

```sh
agentdiff list --thread-state open --last-author human   # open threads awaiting the agent
```

The human reviews and `close`s. A live MCP server (`agentdiff serve-mcp`) is on
the roadmap.

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
