# SPIndlebox

**The SPIndleframe indexer.** SPIndlebox empirically decomposes any codebase — Python,
JavaScript/TypeScript, Go, Rust, Bash — into an **SPI (Serialized Process Index)**: a
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

## Notes & limits

- Bash functions are inherently one signature class (`argv → stdout/exit code`) — correct
  per the model, just degenerate.
- Untyped dynamic code normalizes to `any`, which weakens dedup value; `--strict` surfaces it.
- Grammar wheels are pinned (official tree-sitter org packages only); node-type queries are
  isolated per language module so grammar bumps are localized.
- Related work: Google's [Ramble](https://github.com/GoogleCloudPlatform/ramble) (SC-W '23)
  applies the same data-driven, composable-collections philosophy to HPC experiments;
  SPIndleframe applies it to function-level code structure.
