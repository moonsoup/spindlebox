[SPIndlebox](https://moonsoup.github.io/spindlebox/) · [Guide](guide/index.md) · Plugins

# Plugins — how something else extends SPIndlebox

SPIndlebox indexes functions. Other tools ask other questions of the same
codebases — how many ways in does a project have, which directory is named in
every module, what changes together — and those tools kept rebuilding the same
plumbing underneath: which projects exist, which files belong to one, whether
anything changed, how to read a language. Each copy then had to be fixed
separately, and each fix reached only one of them.

So SPIndlebox carries the plumbing and a plugin brings the questions.

**The dependency runs one way.** A plugin imports spindlebox; spindlebox never
imports a plugin by name. Discovery is by packaging metadata, so a plugin is
*installed*, not registered by editing this tree.

## What a plugin provides

An entry point in the group `spindlebox.plugins`, pointing at a module (or any
object) with these attributes:

| attribute | required | what it is |
|---|---|---|
| `name` | yes | must equal the entry-point name |
| `api` | yes | the contract version it speaks; this spindlebox speaks `PLUGIN_API` |
| `stack_dir` | no | a directory of `*.stack.json` reports |
| `register_ops` | no | `register_ops(register)`, calling `register(op, fn, requires=…, provides=…)` |
| `cli` | no | `cli(argv) -> int`, run as `spindlebox <name> …` |

In `pyproject.toml`:

```toml
[project.entry-points."spindlebox.plugins"]
ziggurat = "ziggurat.spindle_plugin"
```

## What a plugin may not do

These are refusals, not conventions — each is enforced and tested.

- **Ops are namespaced.** Every op must be named `<plugin>.*`, and may not
  replace an existing op. A stack that worked yesterday cannot start meaning
  something else tomorrow because something got installed.
- **Reports are namespaced.** A plugin's stacks are listed as
  `<plugin>:<report>`, so they cannot shadow a built-in report.
- **Command names are reserved.** A plugin may not take a built-in command's
  name, and the built-in commands are matched *before* discovery runs.
  `spindlebox show --span` must not pay for, or be broken by, a plugin import.
- **The index document is not shared state.** `ScaIndex.load` drops keys it
  does not know and `save` rewrites the whole file, and other projects read
  `index.json` by hand. Plugin state goes in `.spi/plugins/<plugin>/`, which
  re-indexing leaves untouched.

A plugin that will not import, declares a different `api`, or misbehaves during
registration is **recorded and skipped** — never fatal, and never silent:

```
spindlebox plugins
ziggurat             NOT LOADED: declares plugin API 2; this spindlebox speaks 1
```

Silence is the failure being designed against. A checker whose plugin failed to
load would report "nothing found" having looked at nothing.

## What installing a plugin *does* change

Exactly one thing, and it is the feature: `spindlebox report --list` gains the
plugin's reports under its `<plugin>:` prefix, and `spindlebox report
<plugin>:<name>` runs them. No built-in row changes, in content or order, and
no other built-in command's output changes at all.

That narrow statement is pinned by `tests/test_plugins.py`
(`test_installing_a_plugin_changes_exactly_one_thing`,
`test_the_quiet_commands_are_untouched_either_way`). It replaces an earlier,
unqualified "no behaviour change to the built-in commands", which an
independent reviewer falsified in one command (#34) — a claim a reviewer can
break that easily costs you the credibility of the claims around it.

## Turning discovery off

`SPINDLEBOX_PLUGINS=none` disables discovery entirely; a comma-separated list
loads only those plugins. The test suite and the executed documentation examples
set it, so an operator's installed plugins cannot change what the docs promise.

## Findings, beside tables

A [SPIndlestack](REPORTING.md) answers with `title`/`columns`/`rows`, which
suits a census. A checker needs to say three things a table has no column for: a
check *could not run* and why, an observation is real but *not decisive*, and
*nothing was read at all* (`scanned: 0` is not `scanned: null`).

So `spindlebox.findings_model` defines schema `spindlebox.findings/1`, and two
ops carry it:

- `render.findings` — `results` → `output`, as markdown or json
- `findings.to_table` — `results` → `title`/`columns`/`rows`, for the formats
  that want a grid, carrying the checks that did not run across as their own rows

## Project facts

`select.projects` answers which projects a run is about: one `root`, every
directory `under` a root, or the registry. Unlike the report collectors' own
iteration, a registered project whose root has gone is **reported as skipped**
rather than dropped, and a project with no index is still a project — a checker
that reads source does not need an SPI at all.
