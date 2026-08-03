[SPIndlebox](https://moonsoup.github.io/spindlebox/) · [Guide](index.md) · Generating

# Generating code

`generate` turns any project's SPI into a skeleton codebase in a target
language. Because every input language normalizes into the same index, **any
indexed language regenerates into any output language** — Python in, Java out;
Go in, Rust out. Output languages are defined by emit profiles
(`spindlebox/generate/emit_profiles/*.json`) — see
[Adding a language](languages.md).

## spindlebox generate

### Synopsis

    spindlebox generate --lang LANG [--out DIR] [--group G] [--project P]

### Options

| Option | Argument | Default | Effect |
|---|---|---|---|
| `--lang` | `rust` \| `java` | required | output backend |
| `--out` | directory | `generated_<lang>/` in cwd | where files land |
| `--group` | group path | whole index | restrict to one group subtree |
| `--pretty` | flag | off | expand bodies onto multiple lines (default: one spindle, one line) |
| `--project` | name | index at/above cwd | registered project |

### Use cases

**A compilable Rust crate from a Python project** — Cargo.toml plus a lib.rs
containing the Ctx struct, one type alias per signature class, a `todo!()`
skeleton and a ctx wrapper per function, op arrays, and any defined pipelines:

    $ spindlebox generate --lang rust --project miniproj_py --out gen_rust
    wrote gen_rust/Cargo.toml
    wrote gen_rust/src/lib.rs

**Cross-language migration in one command** — the same index, Java out:

    $ spindlebox generate --lang java --project miniproj_py --out gen_demo
    wrote gen_demo/Miniproj_py.java

**Port one subsystem** — `--group util.io` emits only that subtree.

### Structure of the output

- **One spindle, one line.** Skeletons, wrappers, op arrays and pipelines each
  emit as a single (long, spindly) line; `--pretty` expands bodies for human
  editing. Blank lines never run more than one deep — whitespace in the output
  is cosmetic and carries no meaning in any target language.
- **`master_spindle()`** — the orchestration root: one function listing every
  op array and pipeline **in load order** (sets first, then pipelines), so a
  generated application has a single authoritative answer to "what runs, in
  what order."
- **`spindle_trace`** — a built-in workflow tracker on `Ctx`: every wrapper
  records its item address as it executes, and every pipeline edge records its
  transfer, so after running any chain the ctx carries the exact path taken
  (e.g. `["app.double", "edge double_result->x", "app.triple"]`).

### What the output is — and isn't

- **Is:** a compiling skeleton (`cargo check` / `javac` clean — enforced
  continuously by the project's own test ladder and the
  [`compile-matrix` report](../REPORTING.md)) with every signature, type
  mapping, doc comment, state-capture classification and ctx contract carried
  over. Bodies are `todo!()` / `throw UnsupportedOperationException` unless
  [body translation](#body-translation) applies.
- **Isn't:** a general transpiler. It ports the *shape* so migration becomes
  mechanical fill-in, and translates only the narrow slice of bodies it can
  prove correct — see below for exactly which.

## Body translation

With `spindlebox index --with-source`, `generate` will translate a function body
instead of stubbing it **when it can prove the result is correct**. Python source
only, into Rust or Java.

    pure.add(a: int, b: int) -> int:  return a + b

    java   public static Long add(Long a, Long b) { return (a + b); }
    rust   pub fn add(a: i64, b: i64) -> i64 { (a + b) }

### The rule is: refuse rather than guess

A wrong translation is far worse than an absent one. A stub fails loudly at the
call site; a mistranslation is a silent defect in ported code. So anything
outside the provable subset falls back to the stub, and that is the *common*
case, not a failure.

**Translated:** a single `return <expr>`, optionally after a docstring; int,
float, bool and str literals; parameter references; `+ - * %` and `//` on
operands proven numeric from the normalized signature; comparisons; `and`,
`or`, `not`; unary minus.

**Refused, and why it matters:**

| Construct | Why it is refused |
|---|---|
| `/` | Python true-divides (`2/2` is `1.0`); Java and Rust integer-divide. Silently wrong for ints. |
| `a == b` on strings | Java `==` compares identity, not value. |
| `a < b < c` | Chained comparison has no direct equivalent. |
| `%` on floats | Sign and remainder semantics differ across targets. |
| `str + str` → Rust | Rust's `+` needs `String + &str` in a specific shape. Allowed for Java, where `+` is well-defined. |
| calls, attributes, subscripts, f-strings, loops, assignments, multiple statements | Not attempted. |
| anything whose operand types cannot be proven from the signature | No guessing from names. |

Type proof comes from the item's normalized signature, so a body is translated
only when every leaf resolves to a known core-1 type. This is also why the 54%
of type slots that normalize to `any` bound how much can ever be translated.

### How it is verified

`tests/test_translate.py` generates Java from a Python fixture, **compiles it,
runs it, and compares the values to the Python originals executed in-process**.
Compiling only proves the output parses; matching the values is what makes this
a claim rather than an aspiration.

Body translation is deliberately narrow today — issue
[#21](https://github.com/moonsoup/spindlebox/issues/21) tracks widening it.
- The Rust backend's emit profile is held byte-identical to the original
  hand-written backend by differential test, so profile-driven output is exactly
  as trusted.

### Exit codes

`0` files written · `1` unknown backend (message lists available ones).

### See also

[Adding an output language](languages.md#output-languages-anatomy-of-an-emit-profile)
— one JSON file · [`call`](model.md#spindlebox-call) executes the same ctx
contract the generated wrappers implement.
