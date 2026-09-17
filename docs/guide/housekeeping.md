[SPIndlebox](https://moonsoup.github.io/spindlebox/) · [Guide](index.md) · Housekeeping

# Housekeeping

The registry, output locations, exit codes, and the small commands.

## Where things land

| Command | Output | Where |
|---|---|---|
| `index <path>` | the SPI | `<path>/.spi/index.json` — a **hidden** folder (`ls -a`; Finder: `Cmd+Shift+.`), plus a registry entry |
| `generate --lang X` | skeleton source | `./generated_X/` in your current directory, or `--out <dir>` |
| `report <name>` | the report | **stdout only** — pass `--out <file>` (or redirect) for a file |
| `pipeline define` | the pipeline | saved into the project's `.spi/index.json` |
| `search` / `show` / `deps` / `validate` / `call` / `gaps` / `workflows` | text | stdout (warnings/errors on stderr) |
| all commands | project registry | `~/.spindlebox/registry.json` |

## The registry

Every `index` run (without `--no-register`) records the project in
`~/.spindlebox/registry.json`; `--all-projects` search and registry-wide reports
read it. `SPINDLEBOX_HOME` overrides the location (useful for isolated testing).
A pre-rebrand `~/.findexer/registry.json` is migrated automatically on first
use.

## spindlebox projects

Manage the registry directly.

### Synopsis

    spindlebox projects [list]
    spindlebox projects add <name> <path>
    spindlebox projects remove <name>
    spindlebox projects prune [--dry-run]

### Use cases

**See everything indexed** — the subcommand is optional, bare `projects` lists:

    $ spindlebox projects list
    miniproj_gaps: .../miniproj_gaps (indexed ...)
    miniproj_mixed: .../miniproj_mixed (indexed ...)
    miniproj_py: .../miniproj_py (indexed ...)

**Adopt an already-indexed checkout** — `projects add` requires an existing
`.spi/index.json` under the path ("run spindlebox index first" otherwise);
`projects remove` only forgets the registry entry, the project's `.spi/` is
untouched.

**Clear out entries whose project has moved or gone.** Projects get renamed,
deleted, or indexed from a temp directory that no longer exists, and every one
of those turns into a `warning: skipping ...` line on each `--all-projects`
search until removed:

    $ spindlebox projects prune --dry-run
    no dangling entries

`prune` removes only the registry entry, never a file on disk — re-indexing a
project registers it again, so the operation is recoverable by construction.
Use `--dry-run` to see what would go first.

## spindlebox install-skill

Copies the packaged skill file to `~/.claude/skills/spindlebox/SKILL.md` so
Claude Code sessions know the spindlebox workflow. No arguments:

```
spindlebox install-skill
installed skill → ~/.claude/skills/spindlebox/SKILL.md
```

## spindlebox plugins

What extends this spindlebox, and what tried to and could not. A plugin is
installed (an entry point in the group `spindlebox.plugins`), never registered
by editing the tree — see [Plugins](../PLUGINS.md) for the contract. Its reports
appear in `spindlebox report` as `<plugin>:<report>`.

    $ spindlebox plugins
    no plugins installed

A plugin that will not import or speaks a different contract version is listed
as `NOT LOADED` with the reason, and everything else carries on: a plugin
extends spindlebox and never gets to break it. Set `SPINDLEBOX_PLUGINS=none` to
ignore installed plugins entirely, or to a comma-separated list to load only
those — the test suite and these examples set it, so what is documented here
does not depend on what an operator happens to have installed.

## The findexer alias

`findexer` is the tool's pre-rebrand name and is kept forever as an identical
alias — every example in this guide works verbatim with `findexer` substituted.
Reading also falls back to legacy `.sca/index.json` indexes; writing always
targets `.spi/`, and sticky ordinals survive the migration.

## Exit codes

| Command | `0` | non-zero |
|---|---|---|
| `index` | indexed, valid | `1` validation errors (index still written) |
| `validate` | valid | `1` any errors |
| `show` | matches printed | `1` no items match |
| `deps`, `call` | resolved / invoked | `1` unresolvable, bad ctx, dispatch error |
| `pipeline define`/`check` | type-sound | `1` type errors (define not saved) / unknown name |
| `report --check` | stack valid | `1` stack errors |
| `report <name>` | rendered | `1` unknown report |
| `generate` | files written | `1` unknown backend |
| `search`, `gaps`, `workflows`, `projects`, `report --list` | always | — (exploratory: they report, you decide) |

Any caught error prints `spindlebox: <message>` to stderr and exits `1`.
