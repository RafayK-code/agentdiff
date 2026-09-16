# Agent guide

How a harness drives agentdiff's CLI, and what the JSON contract contains. This
guide describes the commands and their semantics; it does not prescribe a
workflow — the reader composes their own from these primitives.

## Where comments live

Comments are stored in a `.agentdiff/` directory at the repository root (one
JSONL file per change). That directory is **gitignored**: comments never ship
with the code. All commands below accept `--root PATH` (the repo containing
`.agentdiff/`, default: the current directory).

A **change** is one review: a branch's committed range (`base..HEAD`, default
`HEAD~1..HEAD`). Its id is stable, derived from `(branch, base_revision)`, so
amending the commit does **not** create a new change. A change holds an
append-only list of **versions** (patchsets); each amend appends a version. A
**comment** is anchored to a `(file, side, line range)` on a specific version
and belongs to the change; comments form reply chains (`in_reply_to`), and a
chain is a **thread**.

## Commands

```
agentdiff changes [--branch <name>] [--revision <sha>] [--include-closed]
agentdiff list --change <id> [--revision <rev>] [--file <path>]
                [--state active|resolved|closed]
                [--threads] [--thread-state open|resolved|closed]
                [--last-author human|agent] [--include-closed]
agentdiff export --change <id> | --branch <name>
                 [--format json|markdown] [--out <file>] [--include-closed]
agentdiff show <comment-id>
agentdiff add <file> [--change <id> | --thread <root> | --in-reply-to <id>]
              [--lines START-END] [--side new|old] --message "..." 
              [--author <name>] [--role human|agent]
agentdiff resolve <thread-id> [--role human|agent]
agentdiff reopen <thread-id>  [--role human|agent]
agentdiff close <thread-id>
```

All commands accept `--root PATH`. `list`, `export`, and `changes` hide `CLOSED`
comments unless you pass `--include-closed`.

### `changes` — discovery

Lists stored changes (optionally for one `--branch`), with each change's base
revision, versions, and comment count. Change ids are stable hashes and not
human-guessable, so use `--revision <sha>` (`--commit` is an alias) to find the
change whose versions include a given commit and print just its id:

```sh
agentdiff changes --revision a0373ca2
# chg-1ba1823f4da65ef2
```

An unknown revision is an error; an ambiguous (multi-change) match is an error.

### `list` — inspect comments and threads

`list --change <id>` prints a change's comments. `--revision` and `--file`
narrow the set. `--state` filters an **individual comment's own** state
(`active` / `resolved` / `closed`).

`--threads` groups the (already-filtered) comments into reply threads: each
thread prints a derived status marker (`[open]` / `[resolved]` / `[closed]`), its
last responder (`last=human` / `last=agent`), its root, and its replies indented.

- `--thread-state <state>` shows only threads whose **derived** status matches
  the whole thread, and implies `--threads`.
- `--last-author human|agent` shows only threads whose **last reply** is from
  that role; it implies `--threads` and is orthogonal to `--thread-state`, so the
  two combine.

Note the difference: `--state` filters an individual comment's own state, while
`--thread-state` filters by the thread's derived status. Resolving appends a
`RESOLVED` reply and leaves the root `ACTIVE`, so a resolved thread's root is not
itself `RESOLVED` — use `--thread-state resolved`.

### `export` — the machine contract

`export` requires exactly one of `--change <id>` or `--branch <name>` (the
branch's latest change). The default format is `markdown`; `--format json` is
the stable machine contract described below. `--out <file>` writes to a file
instead of stdout.

### `show` — one comment plus context

`show <comment-id>` prints one comment (naming its `side` and lines) followed by
the canonical diff hunks it anchors to — on-demand surrounding context without
bloating the JSON export. An unknown id exits 1.

### `add` — author a comment or reply

`add` is the only command that creates new comments, and it only creates them on
the **current** version. The selector decides what is created:

- `--change <id>` — a new root comment. Use `--lines START-END` (with
  `--side new|old`, default `new`) for a line range; omit `--lines` for a
  file-level comment.
- `--thread <root>` — a reply to a thread. It attaches to the thread's **tip**,
  so you never have to name a specific comment. The argument must be the thread's
  **root** id; a non-root id is an error.
- `--in-reply-to <id>` — a reply to one exact comment (rare; prefer `--thread`).

`--thread` and `--in-reply-to` are mutually exclusive. When replying, the
parent's anchor is reused (so the file/lines come from the parent), and the new
comment is created on the current version.

The CLI authors as `AGENT` by default (it is the harness surface): `add`,
`resolve`, and `reopen` all take `--role human|agent` to override. `role` is
independent of `--author` (the free-form display name).

### `resolve`, `reopen`, `close` — thread lifecycle

These operate on a **thread**, identified by its **root comment id** — the
`root` field in the export's `threads` array. Passing a non-root id is an error.

- `resolve <thread-id>` appends a `RESOLVED` reply (the thread's derived status
  becomes `resolved`). This is the agent's "addressed" action.
- `reopen <thread-id>` creates a reply on the **current** version, re-anchored to
  the original comment's context. It is how a resolved thread is continued.
- `close <thread-id>` is the human verdict: it sets the whole thread to `CLOSED`
  (retained, but hidden by default). Agents should `resolve`, not `close`.

## Thread semantics

Thread state and last responder are **derived from the latest member** (ordered
by `(created_at, id)`):

- `state` is `open` (latest member `ACTIVE`), `resolved` (latest member
  `RESOLVED`), or `closed` (latest member `CLOSED`).
- `last_author` is the `role` of the latest member.

Because `resolve` appends a `RESOLVED` reply, the root comment stays `ACTIVE`;
always read the thread's derived `state`, not a member's own `state`.

### The `role` / `last_author` signal

`role` (`HUMAN` / `AGENT`) records which side authored a comment. It is set at
authorship — the TUI is the human surface, the CLI is the harness surface — and
is independent of the free-form `author` name.

`last_author` is the thread's action signal:

- an `open` thread whose `last_author` is `HUMAN` is awaiting the agent;
- an `open` thread whose `last_author` is `AGENT` is awaiting the human.

From the shell, the actionable set is the two filters combined:

```sh
agentdiff list --thread-state open --last-author human   # open threads awaiting the agent
```

## JSON export

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

Comment fields:

- `lines` is `[start, end]`, 1-based inclusive. `null` = file-level comment.
- `side` is `OLD` or `NEW` (`null` = file-level): it tells a consumer whether the
  anchor is on the **removed** (old) or **added/current** (new) code.
- `context` is the comment's stored `anchor_snapshot` — the exact lines it was
  written against (`[]` = file-level). For `side: OLD` these are the **removed**
  lines (the "before"); for `side: NEW` the added/current lines. It is projected
  verbatim from the store, never recomputed. Together `side` + `lines` + `context`
  tell a consumer which side, which line numbers, and which exact lines to look
  at.
- `role` is `HUMAN` or `AGENT` (see above); `author` is the free-form name.
- `in_reply_to` is the parent comment id (`null` = thread root).
- `state` is `ACTIVE`, `RESOLVED`, or `CLOSED`; `CLOSED` is omitted by default.
- `drifted: true` means the comment's anchor could not be found in the current
  version (it renders as a file-level note).
- `revision` is the version the comment was created on.

`change` fields: `id`, `branch` (`null` for patch imports), `base_revision`,
`current_revision`, the ordered `versions` (history; `current_revision` is the
last), `approval` (`null` when not approved), and `files` (the current version's
diff).

`threads` gives each reply chain's derived status explicitly — `state` is
`open` / `resolved` / `closed` and `last_author` is the role of the latest
member — so consumers don't have to reconstruct either from `in_reply_to`
ordering. The `comments` array lists the thread's member ids.

The schema is versioned: adding a field is a minor bump, changing/removing a
field or renumbering `lines` is a major bump. See `ARCHITECTURE.md §7` for the
change policy.

## Exit codes

| Case | Exit | Stream |
|---|---|---|
| success | 0 | stdout (output) |
| domain error (selector/change/branch/format) | 1 | stderr |
| bad `--root` (exists, not a directory) | 1 | stderr |
| malformed store record | 1 | stderr |
| I/O error (unwritable `--out`) | 1 | stderr |
| argparse parse failure | 2 | stderr (builtin) |
| bare `agentdiff` on a TTY | 0 | TUI launched |
| bare `agentdiff` piped | 1 | stderr (usage) |

A nonexistent `--root` is a lazy empty store, not an error.
