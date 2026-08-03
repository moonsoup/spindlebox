[SPIndlebox](https://moonsoup.github.io/spindlebox/) · [Guide](index.md) · Querying

# Querying the index

`index` builds the SPI; `show`, `search` and `deps` ask it questions. Every item
gets a sticky **ordinal** (survives re-indexing) and a dotted **address** like
`util.io.Reader.read` — both work anywhere a selector is accepted.

## spindlebox index

Build or refresh a project's SPI. Writes `<path>/.spi/index.json` (a hidden
folder — `ls -a`) and registers the project in `~/.spindlebox/registry.json`.

### Synopsis

    spindlebox index [path] [--name N] [--langs L] [--strict] [--no-register] [--verbose] [--with-source]

### Options

| Option | Argument | Default | Effect |
|---|---|---|---|
| `path` | directory | `.` | project root to index |
| `--name` | string | directory name | project name in the registry |
| `--langs` | csv | all | restrict languages: `python,javascript,typescript,go,rust,bash,java` |
| `--strict` | flag | off | `any`-typed signatures are errors, not warnings |
| `--no-register` | flag | off | skip the central registry entry |
| `--verbose` | flag | off | also print per-item validation warnings |
| `--with-source` | flag | off | also store each item's body text — required for [body translation](generating.md#body-translation) |

`--with-source` roughly doubles index size and nothing but body translation reads
it, so it is off by default. A body is always *locatable* from `file` + `span`
regardless; the flag controls whether it is *captured*. The per-item `hash`
already covers that same text, so staleness detection vouches for it with no
extra machinery.

### Use cases

**Index a project for the first time**

    $ spindlebox index miniproj_py --name miniproj_py
    indexed miniproj_py: 18 items, 13 signature classes, 29 ctx keys, languages: python

**Re-index after edits** — ordinals are sticky: unchanged items keep their
numbers, so saved selectors and pipelines survive.

    $ spindlebox index miniproj_py --name miniproj_py
    indexed miniproj_py: 18 items, 13 signature classes, 29 ctx keys, languages: python

**Gate on typing quality** — with `--strict`, untyped (`any`) signatures fail
the build (exit 1), which makes `index --strict` a CI typing gate.

### Exit codes

`0` indexed and valid · `1` validation errors (the index is still written and
registered, so you can inspect what failed).

### Files that fail to parse

A file with a syntax error is **skipped, not fatal**: indexing continues, the
skip is printed to stderr, and — so an index can never silently pass as
complete — every skipped file is recorded in the SPI itself
(`parse_errors`). `validate` warns about them; `validate --strict` (and
`index --strict`) fails on them. The index covers every *statically
discoverable* declaration; code produced at runtime (eval, metaprogramming,
decorator replacement) is inherently out of scope for a static parser.

### See also

[`validate`](model.md#spindlebox-validate) for re-checking without rebuilding ·
[`projects`](housekeeping.md#spindlebox-projects) for the registry.

## spindlebox show

Show items by ordinal range, address, or group path, with filters.

### Synopsis

    spindlebox show [selector] [--project P] [--group G] [--sig-class S]
                    [--lang L] [--name GLOB] [--state-capture SC]
                    [--deps] [--full] [--json] [--span] [--fail-on-stale]

### Options

| Option | Argument | Default | Effect |
|---|---|---|---|
| `selector` | `'12-40,55'` \| address \| group path | all items | which items |
| `--project` | name | index at/above cwd | registered project to read |
| `--group` | path | — | exact group or group-prefix filter |
| `--sig-class` | sig id | — | exact signature-class filter |
| `--lang` | language | — | language filter |
| `--name` | glob | — | `fnmatch` glob on item name |
| `--state-capture` | value | — | `pure` / `reads_instance` / `mutates_captured` / … |
| `--deps` | flag | off | append a dependency block per item |
| `--full` | flag | off | full JSON dict per item |
| `--json` | flag | off | one JSON array of all matches |
| `--span` | flag | off | `file<TAB>start<TAB>end<TAB>address` per item, for a targeted read |
| `--fail-on-stale` | flag | off | exit non-zero if a shown item's file changed since indexing |

### Reading one function instead of a whole file

Reading whole files is what exhausts a context budget: a 23,000-byte module costs the same
whether you needed one function out of it or all forty. `--span` emits exactly the
coordinates a targeted read needs, so no JSON post-processing is required:

    $ spindlebox show util.io.read_lines --project miniproj_py --span
    util/io.py	...	...	util.io.read_lines

Feed those to whatever reads a line range — `sed -n "$start,${end}p" "$file"`, an editor, or
an agent's file-read tool with an offset and limit.

The listing view carries **shape, not meaning**: bodies are hashed and discarded, and `doc`
holds only the docstring's first line. So `show` tells you what exists and what shape it has;
the span read is where the actual code comes from. Note that `--full` costs *more* than
reading the source file outright — it is for schema inspection, not for reading code.

### Spans and staleness

Each item carries `span: [start_line, end_line]`, which is what makes a targeted
read possible — locate the item, then read only its lines rather than the whole
file. A span is only worth acting on while the file is unchanged, so `show`
prints a warning to stderr when any displayed item comes from a file whose
content hash no longer matches the one recorded at index time:

    warning: 2 file(s) changed since indexing — spans may be wrong: src/cli.py, src/io.py
             refresh with: spindlebox index /path/to/repo

Add `--fail-on-stale` to turn that warning into a non-zero exit, which is what
you want in a script that would otherwise act on bad line numbers. See
[`stale`](#spindlebox-stale) for a whole-tree report.

### Use cases

**Browse the first items** — the line format is
`ordinal address sig_class [language/kind/state→trait] — doc`:

    $ spindlebox show 0-3 --project miniproj_py
        0  app.home  sig:->str  [python/function/pure→fn]  — Locate the findexer home directory.
        1  app.make_counter  sig:->any  [python/function/pure→fn]
        2  app.make_counter.bump  sig:->i64  [python/closure/mutates_captured→FnMut]
        3  app.make_reader  sig:str->any  [python/function/pure→fn]

**Walk one module** by group path:

    $ spindlebox show util.io --project miniproj_py
       12  util.io.read_lines  sig:str->list<str>  [python/function/pure→fn]  — Read lines from a file.
       13  util.io.exists  sig:str->bool  [python/function/pure→fn]  — Check whether a path exists.
    ...

**Find every implementation of one shape** — the cross-language payoff: the same
signature class matches Python, Rust, Go and TypeScript at once:

    $ spindlebox show --sig-class "sig:str->list<str>" --project miniproj_mixed
        2  io.read_lines  sig:str->list<str>  [python/function/pure→fn]  — Read lines from a file.
        8  lib.read_lines  sig:str->list<str>  [rust/function/pure→fn]  — Read lines from a file.
       17  main.ReadLines  sig:str->list<str>  [go/function/pure→fn]  — ReadLines reads lines from a file.
       28  util.readLines  sig:str->list<str>  [typescript/function/pure→fn]

### Exit codes

`0` matches printed · `1` no items match, or `--fail-on-stale` was given and a
shown item's file has changed.

### See also

[`search`](#spindlebox-search) for fuzzy lookup · [`deps`](#spindlebox-deps) for
one item's full dependency picture · [`stale`](#spindlebox-stale) for a
whole-tree freshness report.

## spindlebox stale

Report whether an index still describes the working tree.

### Synopsis

    spindlebox stale [path] [--project P] [--check-new] [--json]

### Options

| Option | Argument | Default | Effect |
|---|---|---|---|
| `path` | directory | cwd | repo to check (searches upwards for `.spi/`) |
| `--project` | name | index at/above cwd | registered project to read |
| `--check-new` | flag | off | also walk the tree for files added since indexing |
| `--json` | flag | off | machine-readable report |

### Why this exists

The index records a content hash per file at index time. `stale` re-hashes and
compares, so you learn that spans have rotted *before* acting on them rather
than after. Content hash is authoritative and mtime is only a pre-filter: a
`git checkout` or `touch` rewrites mtime without changing a byte, and treating
that as a change would make every branch switch look like full invalidation.

By default `stale` reports only on files the index already knows about, because
detecting *additions* means walking the tree. Pass `--check-new` when you want
that too — and note that the default verdict says so, rather than letting a bare
"up to date" imply a check it did not run.

### Use cases

**Check before trusting spans** — a freshly indexed tree verifies clean, and
names what it did not look at:

    $ spindlebox stale --project miniproj_py
    ... up to date (... files verified); new files not checked — re-run with --check-new

**After editing a source file**, the changed file is named so you know which
spans to stop trusting:

    miniproj_py: STALE — 1 changed, 0 missing, 0 new (of 4 indexed)
      changed  util/io.py
    re-index to refresh: spindlebox index

**An index built before staleness tracking existed** carries no file metadata,
which is itself unverifiable — so it is reported rather than silently passed
as clean:

    miniproj_py: index carries no file metadata (built before staleness tracking) — spans cannot be verified; re-index to enable checking

### Exit codes

`0` index matches the tree · `1` stale, missing, or unverifiable.

### See also

[`index`](#spindlebox-index) to refresh · [`show`](#spindlebox-show) and its
`--fail-on-stale` flag for per-query checking.

## spindlebox search

Score-ranked lookup — the anti-bloat check. Before writing a function, ask
whether you already have it, in any language, in any indexed repo.

### Synopsis

    spindlebox search <query> [--project P] [--all-projects]
                      [--sig-class S] [--lang L] [--limit N] [--no-tests] [--json]

### Options

| Option | Argument | Default | Effect |
|---|---|---|---|
| `query` | string | required | matched against name (exact=3, substring=2), address and doc (1) |
| `--project` | name | index at/above cwd | search one project |
| `--all-projects` | flag | off | search every registered project |
| `--sig-class` | sig id | — | restrict to one signature class |
| `--lang` | language | — | restrict to one language |
| `--limit` | int | 25 | truncate results |
| `--no-tests` | flag | off | drop test/spec items — anti-bloat wants product code |
| `--json` | flag | off | JSON array, each item tagged with its `project` |

`--no-tests` matches whole dotted segments (`tests`, `spec`, `conftest`, `__tests__`) plus
`test_*`, `*_test` and `*_spec`. It is segment-based on purpose: a substring match would
also swallow `latest` and `contested`. Off by default, so existing behaviour is unchanged.

### Use cases

**"Do I already have this?" across everything indexed:**

    $ spindlebox search "read" --all-projects --limit 6
    miniproj_mixed:6  io.Reader.read  sig:->list<str>  [python/method/mutates_instance→FnMut]
    miniproj_mixed:11  lib.Reader.read  sig:->list<str>  [rust/method/mutates_instance→FnMut]
    miniproj_mixed:22  main.Reader.Read  sig:->list<str>  [go/method/reads_instance→Fn]
    ...

**Search by shape, not just name** — combine with `--sig-class` to find
functions that both sound right and *fit*.

### Exit codes

Always `0`, even with no matches (search is exploratory, not a gate).

### See also

The [`dup-candidates` report](../REPORTING.md) automates this across the whole
registry.

## spindlebox deps

Everything one item depends on — or, with `--reverse`, everything that depends
on it.

### Synopsis

    spindlebox deps <selector> [--project P] [--reverse]

### Options

| Option | Argument | Default | Effect |
|---|---|---|---|
| `selector` | ordinal or address | required | must resolve to exactly one item |
| `--project` | name | index at/above cwd | registered project to read |
| `--reverse` | flag | off | show callers instead of dependencies |

### Use cases

**Trace what a function needs** — imports, packages, env vars, calls, and its
normalized ctx contract:

    $ spindlebox deps util.io.read_lines --project miniproj_py
       12  util.io.read_lines  sig:str->list<str>  [python/function/pure→fn]  — Read lines from a file.
      imports: json, os, requests
      external packages: requests
      env vars: -
      calls: external:open, external:splitlines, util.io.Reader.read
      ctx requires: {"path": "str"}
      ctx provides: {"read_lines_result": "list<str>"}

**Impact analysis before a refactor** — who calls this?

    $ spindlebox deps util.io.read_lines --project miniproj_py --reverse
    callers of util.io.read_lines:
        4  app.make_reader.read  sig:str->list<str>  [python/closure/reads_captured→Fn]
       16  util.io.Reader.read  sig:->list<str>  [python/method/mutates_instance→FnMut]

### Exit codes

`0` resolved · `1` selector ambiguous or unknown.

### See also

[`gaps`](analysis.md#spindlebox-gaps) finds items with *no* callers
automatically.
