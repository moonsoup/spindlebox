# SPIndlebox

**The SPIndleframe indexer.** SPIndlebox empirically decomposes any codebase — Python,
JavaScript/TypeScript, Go, Rust, Bash, Java — into an **SPI (Serialized Process Index)**: a
nested, addressable, data-driven index of every function, so that:

1. **Nothing gets rebuilt that already exists** — `spindlebox search <concept> --all-projects`
   answers "do I already have this?" across every indexed repo (anti-bloat).
2. **Migration to Rust (or any language) is mechanical** — the SPI carries normalized
   signatures, state-capture classification (Fn/FnMut/FnOnce), and a context-normalized
   calling convention; `spindlebox generate --lang rust` emits a compilable skeleton crate.

## The naming structure

- **SPIndleframe** — the architecture/framework: executable functions, arguments, state,
  and operation groups organized into nested addressable collections, invoked through
  positions or identifiers.
- **SPIndlebox** — this software product, implementing SPIndleframe.
- **SPI** — the Serialized Process Index each indexed project carries (`.spi/index.json`).

## The SPIndleframe model

- **Itemized functions**: every function/method/closure/lambda is an item with a sticky
  ordinal and a hierarchical dotted address (`src.utils.io.Reader.read_lines`).
- **Arrays as operation groups, one element type per array**: within each group, members
  are partitioned by signature class (`op_arrays`) — enforced by `spindlebox validate`.
- **Named groups resembling class members**: packages/modules/classes form the group tree.
- **Ordered pipelines**: `pipeline define` type-checks stage N → N+1 chains (direct return
  → param, or through provided/required ctx keys).
- **Independently callable items**: `spindlebox call <addr> --ctx '{...}'` invokes Python
  items through the normalized context.
- **Compile-time validation**: schema conformance, array homogeneity, signature agreement,
  ctx type consistency — non-zero exit on violation.
- **Context normalization**: every item gets a canonical ctx-in → ctx-out adapter
  (`requires` / `provides` / `param_map` / `return_key`), making heterogeneous functions
  uniform — and mapping directly to `Vec<Box<dyn FnMut(&mut Ctx)>>` in Rust.
- **Signature classes are cross-language**: `def f(p: str) -> list[str]` (Python),
  `func F(p string) []string` (Go), `fn f(p: String) -> Vec<String>` (Rust) all share
  `sig:str->list<str>` under the core-1 type vocabulary.

## Install

```bash
pip3 install -e ".[dev]"
spindlebox install-skill        # global Claude Code skill
```

The `findexer` command remains as a permanent legacy alias (pre-rebrand name).

## Quick start

```bash
spindlebox index ~/Software/myproject     # → myproject/.spi/index.json + registry entry
spindlebox show 0-20
spindlebox search "parse" --all-projects
spindlebox deps src.utils.io.read_lines
spindlebox validate --strict
spindlebox call pure.add --ctx '{"a": 2, "b": 40}'
spindlebox generate --lang rust --out /tmp/port
```

## Compatibility

- Legacy `.sca/index.json` indexes (pre-rebrand) load transparently; new indexes write to
  `.spi/`. Sticky ordinals survive the migration.
- Registry lives at `~/.spindlebox/registry.json` (`SPINDLEBOX_HOME` to override); a
  pre-rebrand `~/.findexer/registry.json` is migrated automatically.

## Adding a language

Both directions are declarative — any indexed language can be regenerated into any
output language (e.g. Go in, Java out): `spindlebox generate --lang java`.

**Output languages** are defined by **emit profiles** (`spindlebox/generate/emit_profiles/*.json`):
identifier/keyword rules, a core-1 → target type table, and code-line templates, consumed
by a generic emit engine (`generate/profile_backend.py`). Rust's emit profile is held
byte-identical to the legacy hand-written backend by differential test; Java output exists
only as a profile and is `javac`-checked in CI and by the slamface harness.

**Input languages** are defined by **extraction profiles** (`spindlebox/extract/profiles/*.json`):
file extensions, tree-sitter grammar wheel, node-role tables, capture-analysis rules, a
core-1 type table, and env-var/import patterns. A generic walker (`extract/profile_lang.py`)
consumes the profile; the handful of genuinely language-specific behaviors live in a shared,
named hook library that profiles reference by name. Adding a language = one JSON profile +
one pinned grammar wheel + corpus entries — no new extractor module. Java is implemented
this way end to end; Go and Bash run through the same walker, differential-tested against
their legacy extractors (which remain as the reference implementations). Python deliberately
stays on stdlib `ast`/`symtable` (richer scope analysis than tree-sitter).

## Notes & limits

- Bash functions are inherently one signature class (`argv → stdout/exit code`) — correct
  per the model, just degenerate.
- Untyped dynamic code normalizes to `any`, which weakens dedup value; `--strict` surfaces it.
- Grammar wheels are pinned (official tree-sitter org packages only); node-type queries are
  isolated per language module so grammar bumps are localized.
- Related work: Google's [Ramble](https://github.com/GoogleCloudPlatform/ramble) (SC-W '23)
  applies the same data-driven, composable-collections philosophy to HPC experiments;
  SPIndleframe applies it to function-level code structure.
