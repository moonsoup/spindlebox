[SPIndlebox](https://moonsoup.github.io/spindlebox/) · [Guide](index.md) · Model & dispatch

# Model & dispatch

The SPIndleframe model makes guarantees, and these commands enforce and exercise
them. `validate` is the compiler: schema conformance, one-element-type-per-array
homogeneity, signature agreement, ctx type consistency — non-zero exit on
violation. `call` executes an item through its normalized **ctx adapter**
(`requires` / `provides` / `param_map` / `return_key`), and `pipeline`
type-checks ordered chains of items at definition time.

## spindlebox validate

Compile-time validation pass over an index.

### Synopsis

    spindlebox validate [path] [--project P] [--strict]

### Options

| Option | Argument | Default | Effect |
|---|---|---|---|
| `path` | directory | — | validate the index under exactly this root (no upward search) |
| `--project` | name | index at/above cwd | used when `path` is omitted |
| `--strict` | flag | off | `any`-typed signatures become errors |

### Use cases

**Routine check** — warnings are informational; the model holds:

    $ spindlebox validate --project miniproj_py
    valid: 20 items, 6 warning(s)

(The warnings go to stderr and name each untyped item — `--verbose` on `index`
shows the same list.)

**Typing gate for CI** — strict mode turns untyped signatures into failures:

    $ spindlebox validate --project miniproj_py --strict
    INVALID: 6 error(s), 0 warning(s)

This exits `1`, so a pipeline step of `spindlebox validate --strict` blocks
merges that add untyped surface.

### Exit codes

`0` valid · `1` any errors (message `INVALID: N error(s), M warning(s)`).

### See also

[`index`](querying.md#spindlebox-index) runs the same validation at build time ·
[`pipeline check`](#spindlebox-pipeline) re-validates one chain.

## spindlebox call

Live-invoke a **Python** item through the normalized context. The ctx dict in;
the ctx dict out, with the item's `return_key` filled. Other languages index and
generate but do not dispatch (there's no in-process runtime for them).

### Synopsis

    spindlebox call <selector> --ctx JSON [--project P]

### Options

| Option | Argument | Default | Effect |
|---|---|---|---|
| `selector` | ordinal or address | required | the item to invoke |
| `--ctx` | JSON object | required | feeds the item's params via its `param_map` |
| `--project` | name | index at/above cwd | registered project |

### Use cases

`call` executes **Python module-level functions only** — methods, closures and
lambdas are represented in the SPI but not callable, and other languages index
and generate but never dispatch. Invoking imports the target module (its
top-level code runs), so only `call` into projects you trust.

**Smoke-test a pure function** — `a` and `b` route to params, the result lands
under the item's `return_key`:

    $ spindlebox call pure.add --ctx '{"a": 2, "b": 40}' --project miniproj_py
    {
     "a": 2,
     "b": 40,
     "add_result": 42
    }

**Exercise a ctx contract** — omit a required key and dispatch fails with the
missing-key error rather than a Python traceback, which is the adapter doing its
job.

### Exit codes

`0` invoked · `1` bad JSON, unresolvable selector, or dispatch error.

### See also

The generated Rust/Java wrappers implement this exact contract —
[`generate`](generating.md#spindlebox-generate).

## spindlebox pipeline

Define, check and list ordered pipelines. A pipeline is a chain of items where
each stage feeds the next — directly (return → param) or through provided /
required ctx keys — and the chain is **type-checked when defined**, not when
run.

### Synopsis

    spindlebox pipeline define <name> <stage> [<stage> ...] [--project P]
    spindlebox pipeline check  <name> [--project P]
    spindlebox pipeline run    <name> --ctx JSON [--project P]
    spindlebox pipeline list   [--project P]

### Options

| Option | Argument | Default | Effect |
|---|---|---|---|
| `name` | string | required (define/check) | pipeline name; re-defining replaces |
| `stages` | ordinals or addresses | required (define) | in execution order |
| `--project` | name | index at/above cwd | registered project |

### Use cases

**Define a two-stage chain** — accepted only if stage N's outputs satisfy stage
N+1's inputs. Defining also computes the pipeline's **data-flow edges** — the
explicit bindings that carry stage N's result into stage N+1's input key
(a ctx-mediated chain needs none; a direct chain gets one):

    $ spindlebox pipeline define readpipe util.io.read_lines util.io.exists --project miniproj_py
    pipeline 'readpipe' defined and type-checked (2 stages, 0 data-flow edge(s))

**Run a pipeline and watch data actually flow** — `double → triple` is a direct
chain: the edge moves `double_result` into `x` between stages, so the answer is
`triple(double(2)) = 12`, not two independent reads of the seed ctx:

    $ spindlebox pipeline define chain pure.double pure.triple --project miniproj_py
    pipeline 'chain' defined and type-checked (2 stages, 1 data-flow edge(s))

    $ spindlebox pipeline run chain --ctx '{"x": 2}' --project miniproj_py
    {
     "x": 4,
     "double_result": 4,
     "triple_result": 12
    }

(`pipeline run` executes Python stages only, like `call`.) The generated Rust
and Java pipelines emit the same edges as transfer ops, and a CI test fills the
generated Rust stubs and executes the chain to assert the same 12.

**See what's defined:**

    $ spindlebox pipeline list --project miniproj_py
    readpipe: util.io.read_lines → util.io.exists [checked]

**Re-check after re-indexing** — `pipeline check readpipe` re-runs the chain's
type validation; if an edit broke the contract, it reports the specific stage
mismatch and exits `1` (and a broken `define` is refused outright — the pipeline
is not saved).

### Exit codes

`0` defined/sound/listed · `1` type errors (define is rolled back) or unknown
pipeline name.

### See also

[`workflows`](analysis.md#spindlebox-workflows) *mines* candidate chains from
the index in `pipeline define`-ready form.
