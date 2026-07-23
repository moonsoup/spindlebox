[SPIndlebox](https://moonsoup.github.io/spindlebox/) · [Guide](index.md) · Querying

# Querying the index

`index` builds the SPI; `show`, `search` and `deps` ask it questions. Every item
gets a sticky **ordinal** (survives re-indexing) and a dotted **address** like
`util.io.Reader.read` — both work anywhere a selector is accepted.

## spindlebox index

Build or refresh a project's SPI. Writes `<path>/.spi/index.json` (a hidden
folder — `ls -a`) and registers the project in `~/.spindlebox/registry.json`.

### Synopsis

    spindlebox index [path] [--name N] [--langs L] [--strict] [--no-register] [--verbose]

### Options

| Option | Argument | Default | Effect |
|---|---|---|---|
| `path` | directory | `.` | project root to index |
| `--name` | string | directory name | project name in the registry |
| `--langs` | csv | all | restrict languages: `python,javascript,typescript,go,rust,bash,java` |
| `--strict` | flag | off | `any`-typed signatures are errors, not warnings |
| `--no-register` | flag | off | skip the central registry entry |
| `--verbose` | flag | off | also print per-item validation warnings |

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

### See also

[`validate`](model.md#spindlebox-validate) for re-checking without rebuilding ·
[`projects`](housekeeping.md#spindlebox-projects) for the registry.

## spindlebox show

Show items by ordinal range, address, or group path, with filters.

### Synopsis

    spindlebox show [selector] [--project P] [--group G] [--sig-class S]
                    [--lang L] [--name GLOB] [--state-capture SC]
                    [--deps] [--full] [--json]

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

`0` matches printed · `1` no items match.

### See also

[`search`](#spindlebox-search) for fuzzy lookup · [`deps`](#spindlebox-deps) for
one item's full dependency picture.

## spindlebox search

Score-ranked lookup — the anti-bloat check. Before writing a function, ask
whether you already have it, in any language, in any indexed repo.

### Synopsis

    spindlebox search <query> [--project P] [--all-projects]
                      [--sig-class S] [--lang L] [--limit N] [--json]

### Options

| Option | Argument | Default | Effect |
|---|---|---|---|
| `query` | string | required | matched against name (exact=3, substring=2), address and doc (1) |
| `--project` | name | index at/above cwd | search one project |
| `--all-projects` | flag | off | search every registered project |
| `--sig-class` | sig id | — | restrict to one signature class |
| `--lang` | language | — | restrict to one language |
| `--limit` | int | 25 | truncate results |
| `--json` | flag | off | JSON array, each item tagged with its `project` |

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
