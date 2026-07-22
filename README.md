# findexer

**Serialized Code Architecture (SCA) indexer.** Empirically indexes every function in an
arbitrary codebase — Python, JavaScript/TypeScript, Go, Rust, Bash — into a nested,
addressable, data-driven structure, so that:

1. **Nothing gets rebuilt that already exists** — `findexer search <concept> --all-projects`
   answers "do I already have this?" across every indexed repo (anti-bloat).
2. **Migration to Rust (or any language) is mechanical** — the index carries normalized
   signatures, state-capture classification (Fn/FnMut/FnOnce), and a context-normalized
   calling convention; `findexer generate --lang rust` emits a compilable skeleton crate.

## The SCA model

- **Itemized functions**: every function/method/closure/lambda is an item with a sticky
  ordinal and a hierarchical dotted address (`src.utils.io.Reader.read_lines`).
- **Arrays as operation groups, one element type per array**: within each group, members
  are partitioned by signature class (`op_arrays`) — enforced by `findexer validate`.
- **Named groups resembling class members**: packages/modules/classes form the group tree.
- **Ordered pipelines**: `pipeline define` type-checks stage N → N+1 chains (direct return
  → param, or through provided/required ctx keys).
- **Independently callable items**: `findexer call <addr> --ctx '{...}'` invokes Python
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
findexer install-skill        # global Claude Code skill
```

## Quick start

```bash
findexer index ~/Software/myproject       # → myproject/.sca/index.json + registry entry
findexer show 0-20
findexer search "parse" --all-projects
findexer deps src.utils.io.read_lines
findexer validate --strict
findexer call pure.add --ctx '{"a": 2, "b": 40}'
findexer generate --lang rust --out /tmp/port
```

## Notes & limits

- Bash functions are inherently one signature class (`argv → stdout/exit code`) — correct
  per the model, just degenerate.
- Untyped dynamic code normalizes to `any`, which weakens dedup value; `--strict` surfaces it.
- Grammar wheels are pinned (official tree-sitter org packages only); node-type queries are
  isolated per language module so grammar bumps are localized.
- Related work: Google's [Ramble](https://github.com/GoogleCloudPlatform/ramble) (SC-W '23)
  applies the same data-driven, composable-collections philosophy to HPC experiments;
  SCA applies it to function-level code structure.
