# spindlebox

- **Category**: personal
- **Path**: `/Users/isme/Software/spindlebox`
- **GitHub**: moonsoup/spindlebox
- **Version**: 1.4.0 · **Tests**: 346 pass / 3 skip (cargo absent) · ruff clean

## What this is

The SPIndleframe indexer. It decomposes a codebase into an **SPI** (Serialized Process
Index) at `<repo>/.spi/index.json` — every statically discoverable function with a
normalized signature, a dependency map, and a **`span: [start_line, end_line]`**.

Two distinct jobs, both legitimate, and they are easy to confuse:

1. **Read-time retrieval** (primary, added 2026-08-02). Locate a function in the index,
   then read *only its lines* instead of the whole file. Measured on projectMan: 1,352
   bytes index-first vs 74,649 for grep-then-read.
2. **Anti-bloat** (original). Before writing a function, check whether one already exists,
   in any language, in any indexed repo.

## Working here

```bash
python3 -m pytest tests/ -q      # must be 346 passed / 3 skipped
ruff check .                     # must be clean
```

**The docs are enforced by tests, and this catches people out.** `tests/test_docs_examples.py`
*executes* every `    $ spindlebox ...` block in `docs/guide/*.md` against fixture projects
and shape-matches the output, and separately diffs every options table against `--help` in
both directions. So:

- Adding a CLI flag **fails the suite** until it is documented in the right options table.
- A documented example that cannot actually run **fails the suite**. Illustrative output
  belongs in an indented block with **no** `$ ` line, or it will be executed.
- Adding a command to `_CMD_DOCS` in that test opts it into docs enforcement.

## Gotchas

- **Ordinals start at 100** on an established index and are sticky/never reused. `show 0-20`
  legitimately matches nothing — the README quick-start is wrong about this (issue #18).
- `discover_files` uses `git ls-files` when a `.git` exists, so gitignored-but-relevant code
  is invisible to the index.
- `.spi/` is gitignored here and in all 19 indexed repos.
- Content hash is authoritative for staleness; **mtime is only a pre-filter**. A `git
  checkout` rewrites mtime without changing a byte, so mtime alone must never invalidate.
- `call_item` does a real `exec_module` of the target file — import-time side effects
  execute. Relevant before anything runs in a container.

## Open issues

- **#17** — `gaps` and `workflows` are majority noise at defaults (208 of 426 gaps are false
  positives; all 171 workflow candidates return identical confidence). Deferred.
- **#18** — README `show 0-20` returns nothing.
- **#19** — an empty project is indistinguishable from a pre-staleness index, so `stale`
  wrongly exits 1 on it.

## The work coming next — read this before starting anything

The dogfooder is being containerized and its instances isolated; per-project memory shrinks
and **the actual memory moves into data and functions**, with an agentic adversary judging
what belongs in the codebase. **spindlebox has to work end to end before that migration.**

**Full brief: `~/Software/rememberall/docs/MEMORY-TO-CODE-MIGRATION.md`.** Read it first.
Memory pointer: `project_memory_to_code_migration` in the memory directory.

What blocks end-to-end today, honestly:

1. **`call` and `pipeline run` are Python-and-module-level-only.** Methods, closures and
   lambdas are rejected by design. Most operational knowledge being migrated is *bash*
   (mount, launchctl, diskutil, ssh), so those procedures cannot become callable items.
2. **There is no data side.** The SPI indexes *functions*. `ctx_schema` types keys; it does
   not hold values. A fact store with provenance does not exist.
   **Default: build it as a separate module beside the indexer, not inside it** — that keeps
   the two reversible and independently testable, and the SPI schema stays about code.
   Do not stop to ask; build it, record the choice and the reason in the module's own
   docstring, and let the adversarial judge challenge it. Reverse the decision if the judge
   makes the case. A wrong architecture call here costs a refactor, not data.
3. **#17 must be fixed if the adversarial judge consumes `gaps`/`workflows`** — otherwise it
   consumes noise.

**The staleness lesson transfers directly.** This index stored a `span` per item and never
checked whether the file had moved: 18% were silently wrong and 36% of the codebase was
missing, with no signal to the caller (#15, fixed in v1.3.0). A fact migrated into a table
("the VPS is 2.25.209.57") has the identical failure mode. Every fact row needs a
verification method and a timestamp, or the same bug is rebuilt in a new place.

**Design input for the adversary:** everything that caught a real error in the session that
built this was a check that *could fail* — a split verifier catching reworded lines, a link
checker finding 16 dead references, ruff catching an import 346 tests missed, a live run
catching 129 files of sibling churn. None came from reasoning about the code. Give the judge
falsifiable checks, not opinions. "Leave it as prose" must be a verdict it can reach.
