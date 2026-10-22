[SPIndlebox](https://moonsoup.github.io/spindlebox/) · [Guide](index.md) · Adding a language

# Adding a language

Both directions are **declarative**. An input language is one JSON extraction
profile consumed by a generic tree-sitter walker
(`spindlebox/extract/profile_lang.py`); an output language is one JSON emit
profile consumed by a generic emitter (`spindlebox/generate/profile_backend.py`).
**Java exists end-to-end as data** — there is no `java_*.py` module anywhere
(a test asserts it), and no AI is involved: adding a language is JSON authoring
plus a pinned grammar wheel plus fixtures.

## Prerequisites, stated honestly

- **An official tree-sitter grammar wheel must exist** for an input language and
  be pinned in `pyproject.toml` (the current pins: `tree-sitter-python`,
  `-javascript`, `-typescript`, `-go`, `-rust`, `-bash`, `-java`, `-c`). No wheel →
  no input language, full stop. Output languages need no grammar at all.
- **Hooks are the escape hatch, not the norm.** A shared named-hook library
  covers constructs that resist declarative description (e.g. Go's multi-value
  returns via `"returns_norm_hook": "go_multi_return"`, Rust's `self` receiver
  states). A typical new profile needs zero or one; every hook is reusable by
  name from any profile.
- **Python is the deliberate exception**: it uses stdlib `ast` + `symtable`
  (richer scope analysis than tree-sitter) and is registered as a native
  extractor rather than a profile.

## Input languages: anatomy of an extraction profile

Profiles live in `spindlebox/extract/profiles/<lang>.json`. The simplest real
case is `go.json`; every key below is quoted from it.

```json
"language": "go",
"extensions": [".go"],
"grammar": {"module": "tree_sitter_go", "attr": "language", "name": "go"},
"walker": true,
"mode": "nested",
"boundaries": ["func_literal", "function_declaration", "method_declaration"]
```

- `extensions` auto-extend the file-discovery map; `grammar` names the wheel and
  its entry attribute. An optional `"builtins": [...]` lists the names the
  language provides without an import (`len`, `append`, `panic` for Go);
  extraction marks a call to one of them `builtin:<name>` instead of
  `external:<name>`, which is how `gaps` tells a builtin from a typo without
  knowing any language. `"stdlib_calls": [...]` is the same for names a
  standard library supplies through a header rather than the language itself
  (`printf`, `malloc` for C): the call stays `external:<name>`, because the code
  is outside the project, and the name is listed on the item's
  `deps.stdlib_calls`. `"entry_points": {"names": [...], "prefixes": [...],
  "file_contains": [...]}` says which items are entered from outside the index
  (Go: `main`, `init`, `Test*`, `Benchmark*`, …); extraction stamps the reason on
  the item as `entry_point` (`name:main`, `prefix:Test`, `file:test`). Python's
  conventions live beside its native extractor. The index lists the markers it
  carries in `project.markers`; `gaps` trusts a marker only when it is listed
  there, and falls back to its old heuristics for an older index.
  An `external_imports` rule may name its `"separators"` (`["::"]`, `["/"]`)
  when import paths are not dotted; without it the rule splits on `.` exactly as
  before. `boundaries` are the node types that open a new function
  scope — the walker never descends past them when analyzing a body.

```json
"imports": [{"node": "import_spec", "field": "path", "strip": "\""}],
"calls": {
  "node": "call_expression",
  "field": "function",
  "pattern": "^[A-Za-z_][\\w]*(\\.[\\w]+)*$",
  "boundaries": ["func_literal"]
}
```

- Declarative rules for import collection and call-graph extraction: which node,
  which field carries the text, what pattern a plausible callee matches.

```json
"params": {
  "field": "parameters",
  "nodes": {
    "parameter_declaration": {"type_field": "type", "names_from_children": "identifier", "fallback": "arg{i}"},
    "variadic_parameter_declaration": {"type_field": "type", "names_from_children": "identifier", "first_only": true, "kind": "variadic", "fallback": "args"}
  }
}
```

- Per-parameter-node extraction rules: where the type lives, where names come
  from, which SPI param kind results.

```json
"declarations": {
  "function_declaration": {"kind": "function", "name": {"field": "name"}, "returns": {"field": "result"}, "state": "pure"},
  "method_declaration": {"handler": "go_method"},
  "func_literal": {"kind": "closure", "name": "<closure>", "returns": {"field": "result"}, "capture": "closure", "floor": "reads_captured", "recurse_scope": "same"}
}
```

- Most declarations are pure data. `method_declaration` shows the hook pattern:
  Go's receiver semantics are genuinely language-specific, so the profile names
  a library hook instead of growing engine flags.

The fuller case is `java.json`, which adds:

- `containers` — node types that build the group tree
  (`class_declaration`, `interface_declaration`, `enum_declaration`,
  `record_declaration`, `annotation_type_declaration`), each with `"role": "class"`;
- `instance` — how instance-state capture is detected (`"member_prefix": "this."`);
- `types` — a table registered into the core-1 normalizer instead of a
  per-language function: `"simple": {"String": "str", "int": "i64", ...}` plus
  container bases (`"list_bases": ["List", "ArrayList", ...]`,
  `"optional_bases": ["Optional", ...]`);
- `env_patterns` / `external_imports` — dependency-mapping rules
  (`"System\\.getenv\\(..."`, stdlib roots to exclude).

The type table is what makes cross-language signature classes work: Java's
`List<String>` and Python's `list[str]` both normalize to `list<str>`, so
`readLines(String)` and `read_lines(path: str)` land in the same
`sig:str->list<str>` class.

The awkward case is `c.json`, and it is worth reading before profiling any
C-family language, because C breaks two assumptions the walker otherwise makes.

- **The name is not in a field.** `char **split_words(const char *text)` nests
  as `function_definition → pointer_declarator → pointer_declarator →
  function_declarator → identifier`, and the parameter list hangs off that
  nested `function_declarator`. The walker resolves a name by a single field
  lookup, so C needs the `c_function` hook: it descends the declarator chain to
  the identifier, walks back up to the `function_declarator` the identifier
  actually belongs to (which is what makes `int (*get_cb(void))(int)` come out
  right), and spells the pointer depth back onto the return type.
- **The grammar cannot parse some real input.** `undefined4 * __cdecl f(x)` is
  a multiplication to tree-sitter-c, because `undefined4` is not one of its
  primitive-type keywords — the whole definition collapses into an `ERROR` node
  and the function vanishes. Ghidra spells nearly every function that way. The
  profile therefore names a `source_hook`, which is given the file text before
  it is parsed and blanks the calling convention where it follows a `*`. **A
  source hook must preserve length**: spans, line numbers and columns all have
  to keep pointing at the file on disk, and a fixup that changes length is
  discarded rather than trusted.

C also shows what `state_capture` means in a language with no closures at all:
`captured` is read as *file scope*, so a function that writes a global or a
static is `mutates_captured`, one that only reads a global or an enum constant
is `reads_captured`, and one confined to its own locals, parameters and callees
is `pure`. On decompiled code that is the cheapest available signal for which
functions share mutable state.

Two type-table keys exist for C's spelling of types: `strip_prefixes` removes
leading spellings that carry no type information (`const `, `struct `) before
every other rule, and `array_suffix: "*"` folds pointer depth, so
`const struct Rect *` reaches `list<obj:Rect>`. Both are absent — and therefore
inert — in every other profile.

## Output languages: anatomy of an emit profile

Emit profiles live in `spindlebox/generate/emit_profiles/<lang>.json`. Keyed to
`java.json`:

- **`ident`** — keyword list, escape scheme (`{"style": "suffix", "with": "_"}`
  for Java vs `{"style": "prefix", "with": "r#"}` for Rust), and per-language
  safety flags discovered by compiling real code:
  `"reserved_member_names": ["clone", "equals", "hashCode", ...]` (a static
  `clone()` illegally hides `Object.clone()`),
  `"unique_result_binding": true` (Java has no let-shadowing; a source param
  named `result` must not collide with the wrapper's local),
  `"reserve_ancestor_names": true` (a nested class may not share an enclosing
  class's name).
- **`types`** — the core-1 → target table:
  `"simple": {"str": "String", "i64": "Long", "unit": "Void", ...}` and
  container formats like `"list": {"format": "java.util.List<{0}>"}`.
- **`templates`** — the code lines themselves, with `${var}` slots: skeleton
  open/close, ctx field, fetch-required/optional, call, store, module open/close,
  op arrays, pipelines.
- **`files`** — what gets written: Java emits one `${root}.java`; Rust emits
  `Cargo.toml` + `src/lib.rs`.

Trust anchor: the Rust emit profile is held **byte-identical** to the original
hand-written Rust backend by a differential test over every fixture project —
the engine earned the right to define Java by reproducing Rust exactly.

## Checklist: add input language X

1. Confirm an official `tree-sitter-x` wheel exists; pin it in `pyproject.toml`.
2. Copy the closest profile — `go.json` for simple C-family shapes, `java.json`
   for container-heavy languages — to `spindlebox/extract/profiles/x.json`.
3. Fill the node-role tables against the grammar's node types (inspect a parse
   tree of a small sample file to learn the names).
4. Create `tests/fixtures/miniproj_x` exercising every construct the profile
   declares.
5. Run `spindlebox report profile-coverage` — it lists any declared-but-
   unexercised node types; iterate until the `missing` column is clean.
6. Add `tests/test_extract_x.py` (mirror `test_extract_java.py`; select items by
   address, never by list position). If X replaces a legacy extractor, use the
   differential pattern in `tests/test_profile_walker.py`.
7. Only if a construct genuinely can't be said declaratively: add (or reuse) a
   named hook in `profile_lang.py`'s library and reference it from the profile.

## Checklist: add output language Y

1. Copy `emit_profiles/java.json` to `y.json`; rewrite the ident rules, type
   table, and templates for Y's syntax.
2. Add `tests/test_generate_y.py` with a compile check
   (mirror `test_generate_java.py`'s `javac` test — generate from
   `miniproj_mixed` and run Y's compiler on the output).
3. `spindlebox generate --lang y --project <anything indexed>` — the backend is
   registered automatically from the profile file.

## The analysis layer is language-agnostic

Any language spindlebox maps must flow through every analysis function
without changing that function. Language knowledge belongs to extraction —
profiles as data, `spindlebox/extract/`, and the `typenorm`/`depmap`
resolution tables — and extraction resolves it into neutral markers:
core-1 types, `builtin:`/`external:`/`ambiguous:` call edges, ctx keys.
The analysis modules (`gaps`, `workflows`, `validate`, `sigclass`, `ctxnorm`,
`reporting`, `findings_model`) read only those normalized fields.

This is enforced, not aspirational. `tests/test_language_agnostic.py` parses
every module under `spindlebox/` except `extract/` and `generate/` and reports
four shapes of language knowledge: a comparison on a `language`/`lang` name or
attribute, a string literal naming a language (profile name, alias or file
extension), `import builtins`, and an import of a `*_lang` extractor module.
Every hit must match an entry in
[`docs/language-agnostic-exceptions.json`](../language-agnostic-exceptions.json)
by module and by the hash of the statement enclosing the hit. Editing an
excepted statement changes its hash and voids the entry; an entry that no
longer matches anything fails the suite too, so the registry cannot rot. The
seven analysis modules may not hold an entry at all. Planting
`if item.language == "go":` in `gaps.py` fails the suite — and the suite
checks that it does.

Exceptions are approved, not declared. An entry is added or re-hashed only in
a fix-verify round, and the Codex verdict accepting that round's commit is the
approval the entry cites (`approval.cycle`, `contract`, `issue`, `round`).
Print the current hits in registry shape with
`python3 tests/test_language_agnostic.py`.

**Parity harness.** `tests/fixtures/miniproj_parity/<language>/` holds the
same tiny program in every language that has an extractor — one directory
per language, so a new profile fails the suite until it has a program there.
Each is indexed alone and run through every analysis; the language-neutral
projections of each result (which items are dead, which calls are
unresolvable, which items are near-duplicates, which chains `workflows`
mines and how strongly) must be identical across languages. The two places a
language legitimately differs are read from its profile, never hard-coded in
the test: a `known_only` call extractor cannot report an unresolvable call,
and a `fixed_signature` profile requires its fixed parameters everywhere.

## Limits

Bash is inherently one signature class (`argv → stdout/exit code`) — correct per
the model, just degenerate. C has no way to say "function pointer with this
signature" in core-1, so `int (*fn)(int)` keeps its raw spelling and normalizes
to `any` rather than to a `fn` that has thrown its arguments away. Untyped dynamic code normalizes to `any`, which
weakens dedup value (`--strict` surfaces it; the `typing-health` report
quantifies it). Grammar wheels are pinned to official tree-sitter org packages
only, and node-type queries are isolated per profile so grammar bumps stay
localized.
