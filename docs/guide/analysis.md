[SPIndlebox](https://moonsoup.github.io/spindlebox/) · [Guide](index.md) · Analysis

# Analysis

Purely index-derived analysis: no code runs, no AST re-parsing — the SPI already
contains the call graph, ctx edges and signature classes these commands read.

## spindlebox gaps

Find gaps in the software: dead items, unprovided ctx keys, unresolvable calls,
near-duplicates, unreachable islands.

### Synopsis

    spindlebox gaps [--project P] [--kind K] [--min-severity S] [--json]

### Options

| Option | Argument | Default | Effect |
|---|---|---|---|
| `--project` | name | index at/above cwd | registered project |
| `--kind` | `dead_item` \| `unprovided_ctx_key` \| `unresolvable_call` \| `near_duplicate` \| `unreachable_island` | all | one gap kind |
| `--min-severity` | `high` \| `medium` \| `low` | low | cutoff (high is most severe) |
| `--json` | flag | off | machine-readable |

The kinds: **dead_item** — no in-index caller, not an entrypoint, no ctx edge,
not a member of a reached function table (a `fn_tables` entry that some item
calls through as `table:<address>`, or any packaging `entry_points` group — #40)
(entry points are the language's own conventions, stamped on each item by
extraction from its profile's `entry_points`: `main` everywhere, `init` and
`Test*` in Go, `test_*`/`cmd_*`/`setup` in Python only; an index built before
these markers existed falls back to the old Python-flavoured name heuristic for every
language); **unprovided_ctx_key** — a required ctx key
nothing provides; **unresolvable_call** — a called name that is neither an item
nor an import nor a language builtin or standard-library name (likely a typo;
builtins arrive from extraction already marked `builtin:`, and names like C's
`printf` arrive listed on `deps.stdlib_calls`, see [languages](languages.md#the-analysis-layer-is-language-agnostic)); **near_duplicate** — same signature class + same
ctx shape + shared name stem; **unreachable_island** — a group of items that no
entry point reaches, though at least one of them has a caller: functions that call
each other (or themselves), or a dead item's private helpers. `dead_item` asks
"does this have any caller?", so such a group reads as live there; this kind asks
"is it reachable?", following every edge kind of
[`emergent`](#spindlebox-emergent) from the entry points, the members of reached
function tables and the items with a ctx edge (#41). One record per group, with
`members` and `ordinals`.

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

A call through a function table (`table:<address>`, matched to the index's
`fn_tables` section) is a fan-out edge to each of the table's `n` members at
`calls` = 1/n — the same split as an ambiguous call, because the index knows the
callee is one of them but not which (#40).

Every candidate also says why it ended: **`truncated`** is `true` when the path
stopped at the 8-stage cap with somewhere left to go, and **`cycle`** lists the
stages of the loop it closed when its next step returns to a stage already on
the path (a function calling itself included), `null` otherwise. The text output
marks them `↺ <address>` and `(truncated at 8)`, a note on stderr says when the
200-candidate walk limit was hit, and a final `... N more` line says how many
candidates `--limit` held back (#41).

### Synopsis

    spindlebox workflows [--project P] [--min-confidence C] [--limit N] [--json]

### Options

| Option | Argument | Default | Effect |
|---|---|---|---|
| `--project` | name | index at/above cwd | registered project |
| `--min-confidence` | float | 0.5 | edge threshold (0.5×calls + 0.4×ctx-coverage + 0.1×group-affinity) |
| `--limit` | int | 50 | max candidates |
| `--json` | flag | off | machine-readable |

### Use cases

**Discover latent chains:**

    $ spindlebox workflows --project miniproj_py --limit 3
    [conf 0.50 str 0.53] (3 stages) app.make_reader.read → util.io.read_lines → util.io.Reader.read

Two numbers, because one is not enough. **`conf`** is the weakest edge on the
chain — it gates admission, so it clusters near `--min-confidence` by
construction and cannot rank anything. **`str`** is the mean edge weight, which
is what actually orders candidates. Ranking by `conf` alone made every
candidate look identical (issue #17).

**Promote a mined chain to a real pipeline** — the output is
`pipeline define`-compatible (ordered addresses), so a candidate becomes a
type-checked pipeline verbatim:

    $ spindlebox pipeline define readpipe util.io.read_lines util.io.exists --project miniproj_py
    pipeline 'readpipe' defined and type-checked (2 stages, 0 data-flow edge(s))

### Exit codes

Always `0`.

### See also

[`pipeline`](model.md#spindlebox-pipeline) — where mined candidates graduate to.

## spindlebox emergent

Behaviour that exists only through composition: every composed chain from each
item to a fixed depth, the cycles in the call graph, and whether the work an
item starts is bounded (#41).

A chain runs through four edge kinds: **call** (a resolved call), **indirect**
(an `ambiguous:` call, credited to each same-named item), **table** (a call
through a `fn_tables` entry, to each member) and **ctx** (an item providing a
ctx key another requires). Chains are walks, so a cycle repeats an address
instead of ending the chain. When a chain goes past `--depth`, the item is
settled by a fixed point over the call graph's strongly connected components:
**`unbounded: n`** with the members of the cycle it enters, or **`finite: k`**,
the most stages on any path, measured over the graph with each component
collapsed to one node. Nothing is capped: `--json` lists every item, and every
chain stopped by `--depth` says so (`continues`).

### Synopsis

    spindlebox emergent [--project P] [--depth D] [--from ADDRESS] [--json]

### Options

| Option | Argument | Default | Effect |
|---|---|---|---|
| `--project` | name | index at/above cwd | registered project |
| `--depth` | int | 4 | stages to enumerate chains to |
| `--from` | address | all items | one item, with its chains listed |
| `--json` | flag | off | machine-readable: `cycles`, and per item `chains` and the verdict |

### Use cases

**Which work is bounded** — one line per item that calls anything; items that
call nothing are counted, not listed:

    $ spindlebox emergent --project miniproj_gaps
    10 items, 5 edges, 0 cycle(s); chains to depth 4
    pipeline.load  finite: 3
    ...
    7 item(s) with no outgoing edge: finite: 1 (shown with --json or --from)

**The chains behind one verdict:**

    $ spindlebox emergent --project miniproj_gaps --from pipeline.load
    ...
    pipeline.load  finite: 3
      pipeline.load → pipeline.clean → pipeline.summarize  (ctx, ctx)

### Exit codes

`0`; `1` when `--from` names no item; `2` when `--depth` is below 1.

### See also

[`gaps`](#spindlebox-gaps) — its `unreachable_island` kind reads this graph ·
[`workflows`](#spindlebox-workflows) — ranked candidates rather than every chain.
