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
pip install agentdiff      # or: pipx install agentdiff
```

## Quickstart

agentdiff reviews **committed** changes — the diff of `HEAD~1..HEAD` (the latest
commit against its parent). Commit your work first.

```sh
# 1. Review the current commit in the TUI and leave comments.
agentdiff

# 2. Confirm your staged comments (comments are staged, not saved
#    immediately — see the TUI guide), then quit.

# 3. Hand the comments to an agent as the JSON contract.
agentdiff export --format json
```

## Docs

- [Agent guide](src/agentdiff/docs/agent-guide.md) — how a harness drives the
  CLI, thread semantics, the `role` / `last_author` signal, and the JSON
  contract.
- [TUI guide](src/agentdiff/docs/tui-guide.md) — every key, the selection model,
  staging vs confirm, the colors, navigation, and the editor. Also in-app via
  `?`.
- [ARCHITECTURE.md](ARCHITECTURE.md) — the source of truth: structure, data
  model, contracts, decisions, and roadmap.

## Development

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'

.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

- `AGENTS.md` — how agents work in this repo.
- `ARCHITECTURE.md` — structure, contracts, and decisions.

## Building the docs

The guides are Markdown under `src/agentdiff/docs/`, which is also the MkDocs
`docs_dir`. The doc tooling (MkDocs + mkdocstrings) is a **dev** dependency, not
a runtime one:

```sh
pip install -e '.[dev]'
mkdocs serve            # live preview at http://127.0.0.1:8000
mkdocs build --strict   # build the site into site/
```

`--strict` turns warnings into errors, so a broken link or a page missing from
`nav` fails the build.

Code docs are **scaffolded, not generated yet** — `mkdocs.yml` already configures
the `mkdocstrings` plugin with `paths: [src]`. Once the planned refactor lands,
add a page that pulls in the public modules with a directive:

````markdown
# API reference

::: agentdiff.model
::: agentdiff.diff
::: agentdiff.anchor
::: agentdiff.store
::: agentdiff.export
````

Each `:::` directive renders that module's docstrings, signatures, and members.

## Status

Working: diff ingestion (committed ranges), the versioned change/comment model
with reply threads, the TUI (viewer + commenting + version history), and the CLI
(discovery, export, authoring, resolve/reopen/close, thread-aware listing and
thread status in the JSON export).

Roadmap: version↔version diff view, side-by-side view, MCP server, optional GUI.
