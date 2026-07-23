---
name: spindlebox
description: SPIndlebox (SPIndleframe indexer) — search existing functions across all indexed projects BEFORE writing any new script/function (anti-bloat check), inspect signatures/dependencies/ctx requirements, live-call Python items, and generate Rust (or other language) skeletons for migration. Use when asked to find existing functionality, index a codebase, check "does this already exist?", trace what a function needs to run, or scaffold a Rust port. Formerly named findexer (that command still works as an alias).
---

# spindlebox — SPI (Serialized Process Index) operations

The `spindlebox` CLI is installed globally (editable pip install from `~/Software/spindlebox`;
`findexer` is a permanent legacy alias). Every operation below works from any directory.
Each indexed project carries its SPI at `<project>/.spi/index.json` (legacy `.sca/` still
loads); the registry of all indexed projects is `~/.spindlebox/registry.json`.

## The anti-bloat rule (primary workflow)

**Before writing ANY new function or script, search for an existing one:**

```bash
spindlebox search "<concept>" --all-projects        # across every registered project
spindlebox search "<name>" --project <name>         # one project
spindlebox search read --sig-class "sig:str->list<str>" --all-projects   # by shape
```

If a hit looks close, inspect it before deciding to build:

```bash
spindlebox show <address|ordinal|12-40> --project <name> --deps
spindlebox deps <address> --project <name>            # imports, packages, env vars, ctx keys
spindlebox deps <address> --project <name> --reverse  # who calls it
```

Only when nothing fits: build new — then re-index so the new function is findable:

```bash
spindlebox index <project-root>      # refresh; ordinals are sticky across rebuilds
```

## Command reference

| Command | Purpose |
|---|---|
| `spindlebox index <path> [--langs py,ts,go,rust,bash] [--strict]` | build/refresh the SPI, register project |
| `spindlebox show <SELECTOR> [--project P] [--json\|--deps\|--full]` | items by ordinal range `12-40,55`, address, or group path; filters: `--group --sig-class --lang --name --state-capture` |
| `spindlebox search <query> [--all-projects]` | ranked name/doc/address search |
| `spindlebox deps <addr> [--reverse]` | requirements for operation / callers |
| `spindlebox validate [<path>] [--strict]` | compile-time validation: op-array homogeneity, sig-class membership, ctx type consistency, pipeline soundness |
| `spindlebox call <addr> --ctx '{"key": val}'` | live-invoke a Python item through the normalized context |
| `spindlebox pipeline define <name> <stage>...` | define + type-check an ordered pipeline |
| `spindlebox gaps [--kind K] [--min-severity S] [--json]` | find gaps: dead items, unprovided ctx keys, unresolvable calls, near-duplicate clusters |
| `spindlebox workflows [--min-confidence C] [--json]` | mine candidate cross-function pipelines (call + ctx chaining, ranked by confidence; `pipeline define`-compatible) |
| `spindlebox generate --lang rust [--out DIR] [--group G]` | skeleton crate: Ctx struct, sig-class aliases, todo!() stubs, Vec<CtxOp> op arrays |
| `spindlebox projects list\|add\|remove` | registry management |

## Notes

- Ordinals never shift or get reused after a re-index (deleted ones are retired), so
  saved range queries stay valid — including across the findexer→spindlebox rebrand.
- `sig_class` ids are language-independent: a Python `def f(p: str) -> list[str]` and a Go
  `func F(p string) []string` share `sig:str->list<str>` — use this to find cross-language
  duplicates before porting.
- `state_capture`/`rust_fn_trait` on each item tells you Fn/FnMut/FnOnce boxing for Rust.
- `spindlebox call` only invokes module-level Python functions; params are fed from the
  `--ctx` JSON via the item's ctx adapter (defaulted params optional).
- The generator's output language is pluggable (`spindlebox/generate/`); `rust` ships first.

