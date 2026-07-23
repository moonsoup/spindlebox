[SPIndlebox](https://moonsoup.github.io/spindlebox/) · [Guide](index.md) · Analysis

# Analysis

Purely index-derived analysis: no code runs, no AST re-parsing — the SPI already
contains the call graph, ctx edges and signature classes these commands read.

## spindlebox gaps

Find gaps in the software: dead items, unprovided ctx keys, unresolvable calls,
near-duplicates.

### Synopsis

    spindlebox gaps [--project P] [--kind K] [--min-severity S] [--json]

### Options

| Option | Argument | Default | Effect |
|---|---|---|---|
| `--project` | name | index at/above cwd | registered project |
| `--kind` | `dead_item` \| `unprovided_ctx_key` \| `unresolvable_call` \| `near_duplicate` | all | one gap kind |
| `--min-severity` | `high` \| `medium` \| `low` | low | cutoff (high is most severe) |
| `--json` | flag | off | machine-readable |

The kinds: **dead_item** — no in-index caller, not an entrypoint (`main`,
`test_*`, `cmd_*`, …), no ctx edge; **unprovided_ctx_key** — a required ctx key
nothing provides; **unresolvable_call** — a called name that is neither an item
nor an import (likely a typo); **near_duplicate** — same signature class + same
ctx shape + shared name stem.

### Use cases

**Full sweep** — one line per gap, `[severity] kind location — detail`:

    $ spindlebox gaps --project miniproj_gaps
    [  high] unprovided_ctx_key   pipeline.orphan  — phantom_result
    [medium] dead_item            pipeline.dangler  — dangler: no in-index caller and no context edge
    ...
    [   low] near_duplicate       pipeline.compute_alpha, pipeline.compute_beta  — 2 items share signature sig:list<str>->i64 and ctx inputs — consolidation candidate
    ...

**Dead-code check in CI** — `--kind dead_item --min-severity medium --json` and
fail the build in your own script if the array is non-empty (the command itself
always exits 0 — it reports, you decide).

### Exit codes

Always `0` — including "no gaps found".

### See also

[`deps --reverse`](querying.md#spindlebox-deps) to inspect one suspected-dead
item · the [`dup-candidates` report](../REPORTING.md) for cross-project
duplication.

## spindlebox workflows

Mine candidate cross-function pipelines from the SPI — chains that are already
latent in the code's call graph and ctx contracts.

### Synopsis

    spindlebox workflows [--project P] [--min-confidence C] [--limit N] [--json]

### Options

| Option | Argument | Default | Effect |
|---|---|---|---|
| `--project` | name | index at/above cwd | registered project |
| `--min-confidence` | float | 0.6 | edge threshold (0.5×calls + 0.4×ctx-coverage + 0.1×same-group) |
| `--limit` | int | 50 | max candidates |
| `--json` | flag | off | machine-readable |

### Use cases

**Discover latent chains:**

    $ spindlebox workflows --project miniproj_py --limit 3
    [conf 0.60] (2 stages) util.io.Reader.read → util.io.read_lines
    [conf 0.60] (2 stages) util.io.read_lines → util.io.Reader.read

**Promote a mined chain to a real pipeline** — the output is
`pipeline define`-compatible (ordered addresses), so a candidate becomes a
type-checked pipeline verbatim:

    $ spindlebox pipeline define readpipe util.io.read_lines util.io.exists --project miniproj_py
    pipeline 'readpipe' defined and type-checked (2 stages, 0 data-flow edge(s))

### Exit codes

Always `0`.

### See also

[`pipeline`](model.md#spindlebox-pipeline) — where mined candidates graduate to.
