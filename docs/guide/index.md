[SPIndlebox](https://moonsoup.github.io/spindlebox/) · Guide

# SPIndlebox Command Guide

SPIndlebox decomposes codebases — Python, TypeScript/JavaScript, Go, Rust, Bash,
Java — into an **SPI** (Serialized Process Index): a typed, addressable index of
every statically discoverable function, method, closure and lambda. Once a project is indexed you can
query it, validate it like a compiler, execute items through a normalized
context, regenerate its shape in another language, mine it for dead code and
latent pipelines, and report on it — all from one command.

The lifecycle, in the order you'll use it:

```
spindlebox index → validate → search/show/deps → call/pipeline → generate → gaps/workflows → report
```

## The command sets

1. **[Querying the index](querying.md)** — `index`, `show`, `search`, `deps`.
   Build the SPI and ask it questions. The anti-bloat check
   ("do I already have this?") lives here.
2. **[Model & dispatch](model.md)** — `validate`, `call`, `pipeline`.
   Prove the model holds — schema, array homogeneity, ctx types — and execute
   items and typed pipelines through the normalized context.
3. **[Generating code](generating.md)** — `generate`.
   Mechanical migration: compilable Rust or Java skeletons from any indexed
   language.
4. **[Analysis](analysis.md)** — `gaps`, `workflows`.
   What's dead, what's unprovided, what's duplicated, and what pipelines are
   already latent in the code.
5. **[Reporting](../REPORTING.md)** — `report` and SPIndlestack authoring.
   Data-defined reports in markdown, CSV, HTML or JSON.
6. **[Housekeeping](housekeeping.md)** — `projects`, `install-skill`, the
   `findexer` alias, exit codes, and where every command's output lands.

## Adding languages

Both directions are declarative: an input language is one JSON extraction
profile; an output language is one JSON emit profile. Java exists end-to-end as
data — no hand-written extractor or backend module, and no AI involved. The
walkthrough and copy-paste checklists are in **[Adding a language](languages.md)**.

## Conventions in this guide

- Examples run against the fixture projects in `tests/fixtures/` (`miniproj_py`,
  `miniproj_mixed`, `miniproj_gaps`), indexed into a clean registry. Lines
  beginning `$ spindlebox` are runnable; the output shown is real, with volatile
  values (timestamps, absolute paths) elided as `...`.
- Almost every command takes `--project <name>` to target a registered project;
  without it, the command searches upward from your current directory for a
  `.spi/index.json`.
- Commands that produce lists usually take `--json` for machine-readable output.
- The documented examples are enforced by `tests/test_docs_examples.py` — if a
  command's flags or output shape change, the docs fail CI until updated.
