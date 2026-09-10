# agentdiff

Human inline comments on a diff, exported for any agent harness.

## CLI

```
agentdiff changes [--branch <name>] [--root <path>]
agentdiff export (--change <id> | --branch <name>) [--format json|markdown] [--out <file>] [--root <path>]
agentdiff --version
```

- `changes` lists every stored change across branches (or one branch's chain
  with `--branch`): branch, chain position `v1..vN`, change id, base→head
  revisions, comment counts, and a `(tip)` marker. Patch imports appear under
  `(no branch)`.
- `export` delivers the §7 JSON contract (`--format json`) or human markdown
  (default) for exactly one target: `--change <id>` (a specific patchset) or
  `--branch <name>` (that branch's tip only). Writes to `--out` or stdout.
  Both read the store at `--root` directly — no checkout required.
- Bare `agentdiff` on a TTY prints a "TUI arrives later" message (the TUI is a
  future slice); piped, it prints usage.

### Exit codes / stderr

- `0` success (output on stdout).
- `1` errors — domain errors (missing/both `export` selectors, unknown
  change/branch/format), a `--root` that exists but is not a directory, a
  malformed store record, or an I/O failure (e.g. unwritable `--out`). The
  message goes to stderr as `agentdiff: <message>`.
- `2` argparse parse failures only.

A nonexistent `--root` is a lazy empty store: `changes` prints `No changes.`
(exit 0); `export` reports the target as unknown (exit 1).
