---
name: findexer
description: Serialized Code Architecture indexer — search existing functions across all indexed projects BEFORE writing any new script/function (anti-bloat check), inspect signatures/dependencies/ctx requirements, live-call Python items, and generate Rust (or other language) skeletons for migration. Use when asked to find existing functionality, index a codebase, check "does this already exist?", trace what a function needs to run, or scaffold a Rust port.
---

# findexer — SCA index operations

The `findexer` CLI is installed globally (editable pip install from `~/Software/Findexer`).
Every operation below works from any directory. The index for each project lives at
`<project>/.sca/index.json`; the registry of all indexed projects is `~/.findexer/registry.json`.

## The anti-bloat rule (primary workflow)

**Before writing ANY new function or script, search for an existing one:**

```bash
findexer search "<concept>" --all-projects        # across every registered project
findexer search "<name>" --project <name>         # one project
findexer search read --sig-class "sig:str->list<str>" --all-projects   # by shape
```

If a hit looks close, inspect it before deciding to build:

```bash
findexer show <address|ordinal|12-40> --project <name> --deps
findexer deps <address> --project <name>            # imports, packages, env vars, ctx keys
findexer deps <address> --project <name> --reverse  # who calls it
```

Only when nothing fits: build new — then re-index so the new function is findable:

```bash
findexer index <project-root>        # refresh; ordinals are sticky across rebuilds
```

## Command reference

| Command | Purpose |
|---|---|
| `findexer index <path> [--langs py,ts,go,rust,bash] [--strict]` | build/refresh `.sca/index.json`, register project |
| `findexer show <SELECTOR> [--project P] [--json\|--deps\|--full]` | items by ordinal range `12-40,55`, address, or group path; filters: `--group --sig-class --lang --name --state-capture` |
| `findexer search <query> [--all-projects]` | ranked name/doc/address search |
| `findexer deps <addr> [--reverse]` | requirements for operation / callers |
| `findexer validate [<path>] [--strict]` | compile-time validation: op-array homogeneity, sig-class membership, ctx type consistency, pipeline soundness |
| `findexer call <addr> --ctx '{"key": val}'` | live-invoke a Python item through the normalized context |
| `findexer pipeline define <name> <stage>...` | define + type-check an ordered pipeline |
| `findexer generate --lang rust [--out DIR] [--group G]` | skeleton crate: Ctx struct, sig-class aliases, todo!() stubs, Vec<CtxOp> op arrays |
| `findexer projects list\|add\|remove` | registry management |

## Notes

- Ordinals never shift or get reused after a re-index (deleted ones are retired), so
  saved range queries stay valid.
- `sig_class` ids are language-independent: a Python `def f(p: str) -> list[str]` and a Go
  `func F(p string) []string` share `sig:str->list<str>` — use this to find cross-language
  duplicates before porting.
- `state_capture`/`rust_fn_trait` on each item tells you Fn/FnMut/FnOnce boxing for Rust.
- `findexer call` only invokes module-level Python functions; params are fed from the
  `--ctx` JSON via the item's ctx adapter (defaulted params optional).
- The generator's output language is pluggable (`findexer/generate/`); `rust` ships first.
