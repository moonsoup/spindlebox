---
name: spindlebox
description: SPIndlebox (SPIndleframe indexer) — read large codebases without burning context: locate a function in the index, then read only its lines instead of the whole file. Also the anti-bloat check (search existing functions across all indexed projects BEFORE writing a new one), signature/dependency/ctx inspection, live Python invocation, and Rust skeleton generation. Use when navigating an unfamiliar or large codebase, finding existing functionality, checking "does this already exist?", tracing what a function needs to run, or scaffolding a Rust port. Formerly named findexer (that command still works as an alias).
---

# spindlebox — SPI (Serialized Process Index) operations

The `spindlebox` CLI is installed globally (editable pip install from `~/Software/spindlebox`;
`findexer` is a permanent legacy alias). Every operation below works from any directory.
Each indexed project carries its SPI at `<project>/.spi/index.json` (legacy `.sca/` still
loads); the registry of all indexed projects is `~/.spindlebox/registry.json`.

## Read-time retrieval (primary workflow)

**Reading whole files is what exhausts a context window.** A 23,000-byte module costs the
same whether you needed one function out of it or all forty. The index exists so you can
locate the one and read only that.

Every item carries `span: [start_line, end_line]`. The loop:

```bash
# 0. never trust a stale index — spans point at line numbers, and lines move
spindlebox stale --project <name>

# 1. locate: a whole module's shape for ~1-2 KB instead of the file's 5-23 KB
spindlebox show <group.path> --project <name>
spindlebox search "<concept>" --project <name>

# 2. get the span of the item you actually need
spindlebox show <address> --project <name> --span
# -> util/io.py	12	18	util.io.read_lines
```

Then read **only those lines** — `Read(file, offset=span[0], limit=span[1]-span[0]+1)` —
rather than opening the file.

Measured on this repo: `show <group>` costs 462–2,391 bytes where the source files run
4,565–22,971 — a 5–14x saving on the locate step, before the targeted read.

### What the index cannot tell you

It stores **shape, not meaning**. No function bodies (they are hashed and discarded), and
`doc` is the docstring's **first line only** — on one measured project just 9% of items had
any doc at all. So the listing answers *"what exists and what shape is it"*; it cannot answer
*"what does this do"* or *"what breaks if I change it"*. That is what the span read is for.

Two corollaries worth internalising:

- **`show --full` is a trap.** It costs *more* than reading the source file (36,044 vs 22,971
  bytes on `cli.py`). The savings live in the plain listing view. Use `--full` for schema
  inspection, never as a substitute for reading code.
- **Stale spans are worse than no index.** A missing index gives you a cache miss; a stale
  one sends you to the wrong lines with no signal. `show`/`deps` warn automatically on a
  changed file; `show --fail-on-stale` exits non-zero. In scripts, use the flag.

## The anti-bloat rule (second workflow)

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
| `spindlebox stale [<path>] [--check-new] [--json]` | is the index still true? exit 1 if changed/missing/unverifiable |
| `spindlebox show <SELECTOR> [--project P] [--json\|--deps\|--full] [--fail-on-stale]` | items by ordinal range `12-40,55`, address, or group path; filters: `--group --sig-class --lang --name --state-capture` |
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
  They start at 100 on an established index, so `show 0-20` may legitimately match nothing.
- `sig_class` ids are language-independent: a Python `def f(p: str) -> list[str]` and a Go
  `func F(p string) []string` share `sig:str->list<str>` — use this to find cross-language
  duplicates before porting. Type fidelity is strong for Python/Go/Java/Rust and weaker for
  TypeScript, where a large share of items normalize to `any`.
- `state_capture`/`rust_fn_trait` on each item tells you Fn/FnMut/FnOnce boxing for Rust.
- `spindlebox call` only invokes module-level Python functions; params are fed from the
  `--ctx` JSON via the item's ctx adapter (defaulted params optional).
- The generator's output language is pluggable (`spindlebox/generate/`); `rust` ships first.
- `gaps` and `workflows` are noisy at default settings (see issue #17) — treat their output
  as candidates to triage, not findings.
