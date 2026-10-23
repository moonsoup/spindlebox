# Translation blockers

**Date:** 2026-10-22 · **spindlebox:** 1.7.0 at `ea07489` · **Status:** draft, every row awaiting owner verification

## Purpose

This is a catalogue of what can stop a translation from language A to language B from
succeeding. Each row gives five things:

1. a minimal example: source snippet → what goes wrong in the target;
2. the index field or analysis that could detect it;
3. whether it is detectable today, with evidence;
4. the GitHub issue, if one exists;
5. a test that would fail while the blocker is present.

`spindlebox generate` converts interfaces, not code (#21), so many rows describe what the
*signature* loses. A body translator would inherit every one of these losses.

## How rows were verified

- **Code citations** (`file:line`) were read at `ea07489` after running `spindlebox index .`
  on a fresh index. Only `pyproject.toml` had been stale.
- **"Observed"** means the snippet was put into a synthetic 8-language fixture project
  (`fx.py`, `fx.go`, `fx.rs`, `fx.ts`, `fx.js`, `Fx.java`, `fx.c`, `fx.sh`), indexed with
  `spindlebox index`, then generated with `spindlebox generate --lang rust|java`. The
  `raw → norm` values and the generated signatures quoted below come from that run. The
  fixture is not committed. Rebuild it from the snippets in the rows.
- **Test names** refer to tests that exist in `tests/` or `gx/datastructs/`. The
  `gx/datastructs/test_ds_index.py` run on this date gave 11 failed / 7 passed. Those
  failures are the sealed round for #44, and they are expected.
- `compile-matrix` is **not** used as evidence anywhere in this file, because it only
  checks that generation did not raise (#22).
- "Today" means one of three things: **yes** (a field in the index records the fact),
  **partial** (some languages or cases are recorded, or only `raw_type` keeps it), or
  **no**.

---

## A. Bodies and verification

| # | Blocker and example | Detects it | Today | Issue | Falsifiable test |
|---|---|---|---|---|---|
| 1 | **Interface-only bodies.** `def width(a: int) -> int: return a * a` → Rust `pub fn width(a: i64) -> i64 { todo!() }`. Only a single `return <expr>` over proven-numeric params translates, and only with `--with-source`. | `Item.source_text` plus `translate.translate_body` | **partial:** `translate.py:1-29` lists the supported subset. Stub emitted at `generate/rust_backend.py:251`. `test_refused_without_captured_source`, `test_unsafe_constructs_are_refused` | #21 (open) | Fixture: a Python function with an `if` and a loop, indexed with `--with-source`. Assert the generated Rust body is not `todo!()` and that it returns the Python result for 3 sample inputs. |
| 2 | **No compile evidence.** The generated crate or Java file may not compile, and nothing reports it. | none (`compile-matrix` checks generation only) | **no:** Rust compile tests skip when cargo is absent (CLAUDE.md "3 skip (cargo absent)") | #22, #27 (open) | Fixture: any multi-language index. Assert `cargo check` and `javac` exit 0 on the generated output, and that the test **fails** (not skips) when the toolchain is missing. |

## B. Numbers

| # | Blocker and example | Detects it | Today | Issue | Falsifiable test |
|---|---|---|---|---|---|
| 3 | **Integer width and sign erased.** Go `func Widths(a uint8, b int32, c uint64) uint64` → every type `i64`, so Rust gets `i64` for a `u64` and loses values above 2^63. Rust `Vec<u8>` → `list<i64>` (not `bytes`). | `Param.raw_type` keeps the width. `Param.norm_type` does not (`typenorm.py:188`, `:272`). | **partial:** observed `uint64=>i64`, `u8=>i64`. `test_rust_unsigned_and_signed_collapse_to_one_type`, `test_go_unsigned_collapses_to_signed` | #24 (open) | Fixture: Go `func F(a uint8) uint64`. Assert `norm_type` of `a` differs from Go `int`, or that the index carries a width/sign diagnostic for it. |
| 4 | **int vs number.** Python `def f(x: int) -> int` and TS `function f(x: number): number` land in different sig_classes, so cross-language matching misses them. | `typenorm.py:44` (`int→i64`) vs `:108` (`number→f64`), and `sigclass.py` | **yes (the divergence is visible):** `test_python_int_and_typescript_number_disagree` | #26 (open) | Fixture: the two functions above. Assert they share a `sig_class`, or that the index marks the TS param as "integer-or-float". |
| 5 | **Arbitrary-precision integers truncated.** Python `int`, TS `bigint` and Java `BigInteger` all become `i64`, so `2**70` overflows in the Rust port. | `Param.raw_type` only | **partial:** observed TS `bigint=>i64` (`typenorm.py:110`). Java `BigInteger→i64` is in `extract/profiles/java.json` `types.simple`. | none (adjacent to #24) | Fixture: TS `function big(x: bigint): bigint`. Assert `norm_type` is not `i64` (for example a `bigint` core-1 type) and Rust generation does not emit `i64`. |
| 6 | **Float semantics.** Rust `f32` widens to `f64`, so results differ in the last bits. Python `a / b` on ints is true division, while Java and Rust integer-divide. | `typenorm.py:274`, `translate.py` refusal list | **partial:** `test_bytearray_loses_mutability_and_f32_widens` (the widening is pinned, not flagged). `/` is refused, see `test_division_refusal_is_the_important_one`. | none ("noted not filed" in `tests/test_conversion_fidelity.py`) | Fixture: Rust `fn h(x: f32) -> f32`. Assert the generated Java uses `float`/`Float`, not `Double`. |
| 7 | **Overflow behaviour.** Rust `a.wrapping_add(1)` wraps, Java `int` wraps silently, Python promotes and Rust debug builds panic. The same `+` means different things. | `Deps.calls` records `external:a.wrapping_add`, nothing else | **no:** observed `wrap(a: u8)` → `calls=['external:a.wrapping_add']`, with no overflow flag | none | Fixture: Rust `fn w(a: u8) -> u8 { a.wrapping_add(1) }`. Assert the item carries an overflow-semantics marker (`wrapping`), and that a translated body for `u8` 255 returns 0. |

## C. Type shapes

| # | Blocker and example | Detects it | Today | Issue | Falsifiable test |
|---|---|---|---|---|---|
| 8 | **Multi-arm union collapse.** `def f(x: int \| str \| None)` and TS `string \| number \| boolean` → `any` → `serde_json::Value` / `Object`. | `typenorm.py:65-70` (py) and `:119-126` (ts) | **partial:** `raw_type` keeps the arms. `test_three_arm_union_loses_all_type_information`, `test_typescript_multi_arm_union_also_collapses` | #28 (open) | Fixture: the Python signature above. Assert `norm_type` names all three arms (for example a `union<i64,str>` inside an `option`) and is not `any`. |
| 9 | **User data structures not declared.** `@dataclass class Money: amount: int; currency: str` → index has no `types` section. A param of type `Money` becomes `obj:Money` → `serde_json::Value`. | `types` section (does not exist), `obj:<Name>` in `norm_type` | **no:** `ScaIndex` has no `types` field (`schema.py:352-390`). `rust_backend.py:134` maps `obj:` to `serde_json::Value`. `gx/datastructs` 11 failed. | #44, #45 (open) | Already written: `gx/datastructs/test_ds_index.py::test_types_section_shape` and `test_ds_replicate.py::test_generated_signatures_use_the_model_types`. |
| 10 | **Generic functions erased.** `fn ident<T: Clone>(x: T) -> T`, `def ident(x: T) -> T`, Go `func Ident[T any] (x T) T` → `obj:T` → `serde_json::Value`. Both the type parameter and its bound are lost. | `Param.norm_type` (`obj:T`, indistinguishable from a struct named `T`) | **no:** observed `x:T=>obj:T` in py, go, rust and ts. No type-parameter field on `Item`. | none (#44 covers `type_params` on *types* only, per `register.json` DS-SHAPE) | Fixture: Rust `fn ident<T: Clone>(x: T) -> T`. Assert the item records `type_params: ["T"]` with bound `Clone`, and the generated Java is `<T> T ident(T x)`. |
| 11 | **Nullability lost or invented.** TS `opt(x?: string)` → `str` (the `?` is dropped). Go `*Point` → `obj:Point` (nil is dropped, `typenorm.py:164`). Java `i64` is emitted as boxed `Long`, so every Java param becomes nullable. | `Param.norm_type` `option<T>`, `Param.default` | **partial:** Python `Optional[int]`→`option<i64>` and TS `string \| null`→`option<str>` are preserved (observed). TS `x?` → `x:string=>str[positional]` (observed). Java `"i64": "Long"` at `generate/emit_profiles/java.json:110`. | none | Fixture: TS `function o(x?: string)`. Assert `norm_type == "option<str>"`. Also Go `func P(p *Point)`: assert `option<obj:Point>` or a pointer marker. |
| 12 | **Qualified wrapper paths swallow the inner type.** Rust `std::sync::Arc<std::sync::Mutex<HashMap<String,i32>>>` → `obj:std::sync::Arc`, so the map type is lost entirely. | `typenorm._rust` `_RUST_WRAPPERS` (`typenorm.py:220`, `:251`) compares the unqualified base | **no (defect):** observed `=>obj:std::sync::Arc`. Unqualified `Arc<…>` is unwrapped. | none | Fixture: the signature above. Assert `norm_type == normalize("Arc<Mutex<HashMap<String,i32>>>", "rust")`. |
| 13 | **Go return types bypass the core-1 guard.** `func Chans(...) <-chan string` → returns `obj:<-chan string`. This is not valid core-1 (it contains a space and `-`), so it is neither erased nor typed. | `typenorm._is_clean_core1` is applied in `normalize` (`:402`) but not in `go_return` (`:201-212`, called from `extract/profile_lang.py:699`) | **no (defect):** observed. Params are erased to `any`, consistent with #29. | none (related #29) | Fixture: Go `func C() <-chan string`. Assert `_is_clean_core1(returns.norm_type)` for every item in the index. |

## D. Memory model

| # | Blocker and example | Detects it | Today | Issue | Falsifiable test |
|---|---|---|---|---|---|
| 14 | **Borrows and mutability stripped.** `fn borrow(x: &mut Vec<u8>, y: &str)` → `list<i64>`, `str`. Rust output `borrow(x: Vec<i64>, y: String)` takes ownership, so the caller loses `x`. | `Param.raw_type` keeps `&mut`. `typenorm.py:229-235` strips it. | **partial:** `test_rust_borrow_and_mutability_are_stripped`. Observed. | #30 (open) | Fixture: the Rust signature above. Assert the param records `borrow: "mut"`, and the regenerated Rust takes `&mut Vec<u8>`. |
| 15 | **Mutation through a parameter (aliasing).** `def mutate(xs: list[int]) -> None: xs.append(1)`: the caller sees the change in Python and Java, but not in a by-value Rust or Go port. | `Item.state_capture` (`schema.py:14-17`) covers captured and instance state only | **no:** observed `mutate` → `state=pure`. `mutates_instance` is detected for Go `(p *Point) Move` (observed). | none | Fixture: the Python function above. Assert `state_capture` (or a per-param flag) marks `xs` as mutated. |
| 16 | **Ownership wrappers and pointers erased.** `Box<T>`, `Rc<T>`, `Arc<T>`, `RefCell<T>` and `Mutex<T>` all normalize to `T` (`typenorm.py:220`, `:251`). C `int *out` → `list<i64>`, so the out-parameter becomes a by-value list. | `Param.raw_type` only | **partial:** observed C `int *=>list<i64>`, generated `fill(out: Vec<i64>, n: i64)`. | none (adjacent to #30) | Fixture: C `void fill(int *out, int n)`. Assert the generated Rust takes `&mut` (or `&mut [i64]`) and not `Vec<i64>`. |
| 17 | **Method receivers flattened.** Rust `&self`, Go value receiver `(p Point)` and pointer receiver `(p *Point)` are all emitted as `recv: &mut serde_json::Value`. Python `self` normalizes to `any`, and Rust `&self` to `obj:self`. | `Item.state_capture` (`reads_instance`/`mutates_instance`), `Item.rust_fn_trait` | **partial:** detected (observed `Move`=`mutates_instance`, `Len`=`reads_instance`) but ignored by `rust_backend.py:238` | none | Fixture: Go `func (p Point) Len() int`. Assert the generated Rust receiver is `&self` (not `&mut`) and is not typed `serde_json::Value`. |

## E. Errors, async, concurrency

| # | Blocker and example | Detects it | Today | Issue | Falsifiable test |
|---|---|---|---|---|---|
| 18 | **Error models.** Python `raise ValueError` and Java `void io() throws IOException` are invisible in the signature. Go `(int, error)` → `result<i64,error>` is detected, but Java emit drops the error side: `Pair()` → `Long Pair()`. | `Signature.returns.norm_type` `result<T,E>`, `Deps.calls` | **partial:** Go and Rust Result are detected (observed, `typenorm.py:201-212`, `:263-266`). Python raise shows only as `builtin:ValueError` in `calls` (observed). Java `throws` is not recorded (observed `io () -> unit`). Java emit uses `"result": {"format": "{0}"}` (`generate/emit_profiles/java.json:137`). | none | Fixture: Java `void io() throws IOException` and Python `def r(): raise ValueError`. Assert each item records `raises: [...]`. Also assert Go `Pair()` → Java signature declares `throws` or returns a result type. |
| 19 | **Async erased.** `async def fetch`, TS `async … Promise<string>` and Rust `async fn later() -> u32` all emit synchronous fns (`later() -> i64`, `later_o54() -> String`). `Promise`, `Awaitable` and `CompletableFuture` are unwrapped. A JS function that returns a Promise without `async` is `is_async=False`. | `Signature.is_async` | **partial:** set for py, ts, js and rust (observed). `go_lang.py:150` hard-codes `False`. Java profile declares no `is_async`. Unwrapping at `typenorm.py:97`, `:140` and java.json `unwrap_bases`. Generator never reads `is_async` (grep of `generate/` finds no use). | none | Fixture: Rust `async fn later() -> u32`. Assert the generated Rust is `async fn` and the Java returns `CompletableFuture<Long>`. |
| 20 | **Go channels erased.** `func Chans(in chan int, out chan<- string)` → both params `any` → `serde_json::Value`. | `typenorm.py:196` + `_is_clean_core1` | **partial:** `raw_type` keeps it. `test_go_channel_is_erased_to_any`, `test_directional_channels_also_erased` | #29 (open) | Fixture: the signature above. Assert `norm_type` is a channel type carrying element type and direction, not `any`. |
| 21 | **Goroutines and threads.** `func Spawn(f func()) { go f() }` records only `param:f`, so the `go` (spawn) is lost. Java `Thread` → `obj:Thread`. Unqualified Rust `Arc<Mutex<T>>` → `T`, so shared-state synchronisation is lost. | `Deps.calls`, `Item.takes_fn` | **no:** observed `Spawn calls=['param:f']` with no spawn marker | none | Fixture: the Go function above. Assert the item records a concurrency construct (`spawns: true` or a `go:` call edge). |

## F. Functions as values (closed #39/#40/#41)

| # | Blocker and example | Detects it | Today | Issue | Falsifiable test |
|---|---|---|---|---|---|
| 22 | **Higher-order functions, closures, decorators.** `def apply(f: Callable, x)` or a closure returned from a factory. The target needs `impl Fn` or `Function<…>`, but the generator maps `fn` → `serde_json::Value` / `Object`. | `Item.decorators`, `parent`, `takes_fn`, `returns_fn`, `param:` call edges, `ScaIndex.constructs` | **yes for detection:** `tests/test_meta_functions.py` (`test_decorators`, `test_closure_parent`, `test_takes_fn`, `test_returns_fn`, `test_param_calls`) across languages. **No for generation:** `rust_backend.py:111` and java.json `"fn": "Object"`. | #39 closed (detection) | Fixture: Python `def apply(f: Callable[[int], int], x: int) -> int`. Assert the Rust signature types `f` as `impl Fn(i64) -> i64` (or `fn(i64) -> i64`). |
| 23 | **Function tables (dispatch dicts, registries, entry points).** `OPS = {"add": add, "sub": sub}; f = OPS[k]; f(a, b)`. The target needs a typed map of fn pointers or a `match`. | `ScaIndex.fn_tables` (`FnTable.kind/members/key_type`), `table:` call edges, `fn_tables.py` | **yes** for py, go, rust, js, ts and c (`test_fn_tables.py::test_profile_languages_detect_dict_and_list_tables`, `test_python_module_dict_of_functions`). **No** for Java. Generator does not read `fn_tables` (grep of `generate/` is empty). | #40 closed; #42 open (Java) | Fixture: Java `Map<String, Function<Integer,Integer>> OPS = Map.of("inc", Fx::inc)`. Assert one `fn_tables` entry with member `Fx.inc`. Also assert generated Rust declares an `OPS` map. |
| 24 | **Recursion and composition depth.** `def rec(n): return rec(n-1)` and mutual recursion. Python's recursion limit, Rust's stack and the absence of TCO differ, so deep recursion that works in one language overflows in another. | `callgraph.classify` (`unbounded` / `finite: k`), `callgraph.strongly_connected`, `emergent` | **yes, with false positives:** `test_direct_recursion_is_visible`, `test_mutual_recursion_is_unbounded`, `test_six_deep_chain_is_finite_6`. Name-ambiguous calls create false cycles. | #41 closed; #43 open | Fixture: two unrelated `helper()` functions in different modules, neither recursive. Assert `emergent` reports no cycle containing them (fails today per #43). |

## G. Dynamic features

| # | Blocker and example | Detects it | Today | Issue | Falsifiable test |
|---|---|---|---|---|---|
| 25 | **Decorators with side effects.** `@functools.lru_cache` (memoisation) and `@app.route('/x')` (registration at import). The target has no equivalent, and the behaviour silently disappears. | `Item.decorators` (expression text) | **partial:** observed `decorators: ['functools.lru_cache(maxsize=None)']`. The semantics are not classified. | none | Fixture: the decorated `cached(n)`. Assert the generated target carries a marker (comment or attribute) naming the dropped decorator, or that generation refuses. |
| 26 | **eval / reflection.** `def evaluate(s): return eval(s)`, `getattr(obj, name)()` or Java reflection cannot be translated statically. | `Deps.calls` `builtin:` edges | **partial:** observed `calls=['builtin:eval']`. There is no "dynamic" classification, and `getattr`/`Reflect` are just more builtins. | none | Fixture: the function above. Assert the item is flagged `dynamic: true` and `generate` emits a refusal note, not a typed stub. |
| 27 | **Macros.** Rust `macro_rules! sq` used as `sq!(a)`. The call is invisible, so the dependency is missing. Same for C preprocessor macros. | `Deps.calls` | **no:** observed `usesq` → `calls=[]` | none | Fixture: the Rust macro above. Assert `usesq` has a call edge to `sq!` (a `macro:sq` edge). |

## H. Calling conventions

| # | Blocker and example | Detects it | Today | Issue | Falsifiable test |
|---|---|---|---|---|---|
| 28 | **Overloading.** Java `int over(int a)` and `int over(String s)`. Rust has no overloads, so the generator renames the second to `over_o4`, and every caller of it breaks. | address suffix `~N` (`Fx.Fx.over~2`) | **partial:** observed. `~N` is also used for same-named items in different languages or files (observed `fx.opt~2`, `fx.opt~3`), so it does not specifically mean "overload". | none | Fixture: the Java pair above. Assert both items are marked `overload_of` the same name, and the Rust output uses a trait or a per-type name derived from the param types, not an ordinal. |
| 29 | **Default values lost.** `def opt(x=None, *, flag=False)` and JS `function dflt(a, b = 1)`. Rust and Java have no defaults. The ctx op uses `unwrap_or_default()`, so `b` becomes `0`/`Null`, not `1`. | `Param.default`, `Param.kind == "keyword"` | **yes for detection** (observed `b=1`, `flag:keyword=False`). **No for generation:** `rust_backend.py:287` `unwrap_or_default()`. | none | Fixture: JS `function dflt(a, b = 1)`. Assert the generated Rust ctx op falls back to `1` (or that a builder/overload with the default is emitted). |
| 30 | **Varargs mis-typed.** TS `rest(...xs: string[])` → `list<list<str>>` → `Vec<Vec<String>>`, because the array annotation is wrapped again. Go `...string`, Java `String...` and Python `*args: int` are correct. | `Param.kind == "variadic"`, `extract/__init__.py:92-97` | **no (defect, TS only):** observed. Other languages are correct (observed). | none | Fixture: the TS function above. Assert `norm_type == "list<str>"`. |
| 31 | **kwargs dropped.** `def varkw(a, *args, b=2, **kw)` → Rust `varkw(a, args, b)`. The `kw` param is silently removed. | `Param.kind == "kwvariadic"` → `map<str,any>` | **yes for detection. No for generation:** `rust_backend.py:222` and `profile_backend.py:240` skip `kwvariadic`. | none | Fixture: the Python function above. Assert the generated Rust and Java signatures have 4 params, with `kw` as a map. |

## I. Structure, strings, libraries

| # | Blocker and example | Detects it | Today | Issue | Falsifiable test |
|---|---|---|---|---|---|
| 32 | **Inheritance, traits, embedding.** `class Sq(Base)` overriding `area`, Rust `impl Shape for S`, Go `struct Named { Point; … }`. Output is unrelated `mod Base`/`mod Sq`/`mod S` with no trait and no dispatch. | `Group` (`schema.py:256-262`: name, kind, path, members only) | **no:** no bases field. Rust `impl_item` takes `name_field: "type"` (`extract/profiles/rust.json:39-42`), so the trait name is dropped. Observed separate mods. | none (structure of types overlaps #44) | Fixture: Python `class Sq(Base)` and Rust `impl Shape for S`. Assert group `Sq` records `bases: ["Base"]` and group `S` records `implements: ["Shape"]`. |
| 33 | **Visibility and initialisation order.** Module-level statements (registration, config reads) run at import in Python and JS, at `init()` in Go, and never in Rust. Public vs private is not recorded. | `ITEM_KINDS` includes `script_main` (`schema.py:12`) | **no:** no extractor emits `script_main` (grep: only `schema.py`, `extract/base.py`, `gaps.py` mention it). No visibility field. | none | Fixture: Python module with top-level `REGISTRY.append(f)` and Go `func init()`. Assert a `script_main` item exists for the Python module and the Go `init` is marked as run-at-load. |
| 34 | **String encoding and indexing.** `len(s)` counts code points in Python, UTF-16 units in JS/Java and bytes in Go/Rust. `char` → `str` in Rust, Java and C (`typenorm.py:270`, java.json `"char": "str"`), so a C `char` byte becomes a string. Go `[]rune` → `list<i64>`. | `Deps.calls` (`builtin:len`) | **no:** observed `strlen` → `builtin:len`, but call arguments are not recorded (`callgraph.py` docstring: "the index does not record the argument"), so `len` on a `str` cannot be identified. | none | Fixture: Python `def n(s: str) -> int: return len(s)` translated to Rust. Assert the translated body uses `s.chars().count()`, not `s.len()`, and returns 1 for `"é"`. |
| 35 | **Stdlib and third-party API mapping.** `functools.lru_cache`, `os.path.join`, `requests.get`: the index says a call leaves the project, but nothing maps it to a target equivalent. | `Deps.calls` (`builtin:`/`external:`), `Deps.stdlib_calls` (`schema.py:127`), `Deps.external_packages` | **partial:** `stdlib_calls` is declared only by the C profile (`extract/profiles/c.json`). Other languages use `builtin:` markers (#38). No mapping table exists. | #38 closed (markers only) | Fixture: Python `os.path.join(a, b)`. Assert a mapping lookup returns `std::path::Path::join` for Rust, and that `generate` lists unmapped external calls. |
| 36 | **Shell process model.** Bash `greet() { echo "hi $1"; }` has no types. Every param becomes `list<str>` and the return becomes `result<str,i64>` (stdout plus exit code). Pipes, subshells and environment mutation have no function equivalent. | `typenorm.register_fixed`, `Deps.env_vars` | **partial:** observed `args=>list<str>`, `=>result<str,i64>`. Env vars are recorded. | none (CLAUDE.md "what blocks end-to-end" item 1) | Fixture: bash function that `export`s a var and is piped. Assert the item records `env_writes` and `reads_stdin`. |

---

## Rows that need new work

These rows have **no existing issue** and **no detection today** ("no" above):

- **7** Overflow behaviour (wrapping/panic/promote) is not recorded.
- **10** Generic function type parameters and bounds are erased to `obj:T`.
- **12** Defect: qualified Rust wrapper paths (`std::sync::Arc<…>`) swallow the inner type.
- **13** Defect: Go return types bypass the `_is_clean_core1` guard (`obj:<-chan string`).
- **15** Mutation through a parameter is invisible (`state_capture` stays `pure`).
- **21** Goroutine/thread spawns and shared-state sync are not recorded.
- **27** Macro invocations are not call edges.
- **30** Defect: TS rest params are double-wrapped (`list<list<str>>`).
- **32** Inheritance, trait impls and embedding are not recorded.
- **33** Module init code and visibility are not recorded (`script_main` is never emitted).
- **34** String length and indexing semantics are not detectable (call args are not recorded).

These rows have **no issue but partial detection**, and the gap is in generation or classification:

- 5 (arbitrary precision)
- 6 (f32 widening, noted but not filed)
- 11 (nullability)
- 16 (ownership wrappers)
- 17 (receivers)
- 18 (error models)
- 19 (async)
- 25 (side-effecting decorators)
- 26 (eval/reflection)
- 28 (overloads)
- 29 (defaults)
- 31 (kwargs dropped)
- 35 (API mapping)
- 36 (shell model)

## Filed (2026-10-22)

- #46: the normalization defects in rows 12, 13 and 30.
- #47: generation silently drops information (rows 18 and 31).
- #48: C data types, deferred from #44.
- #49: every other "needs new work" row above, deferred with this document as the reason.
- Data structures (shown and replicated) are covered by the sealed round `gx/datastructs`: #44 (index) and #45 (generate).
