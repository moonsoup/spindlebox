"""C is extracted from its declarative profile plus the `c_*` hooks.

Only the name/parameter lookup needs code: C hides the function name two or more
levels down a declarator chain, and hangs the parameter list off the nested
`function_declarator`, so the walker's direct field lookup cannot reach either.
Everything else — types, imports, calls, docs, writes — is JSON.
"""

from pathlib import Path

import pytest

from spindlebox.extract import build_index
from spindlebox.extract.profile_lang import extract_with_profile
from spindlebox.extract.profile_registry import profile_for
from spindlebox.typenorm import normalize

FIXTURE = Path(__file__).parent / "fixtures" / "miniproj_c"


@pytest.fixture(scope="module")
def idx():
    return build_index(FIXTURE, project_name="miniproj_c", langs=["c"])


def by_addr(idx, address):
    item = idx.item_by_address(address)
    assert item is not None, f"no item at {address}; have {[i.address for i in idx.items]}"
    return item


def parse_c(source: str, rel: str = "snippet.c"):
    return extract_with_profile(profile_for("c"), rel, source)


# ------------------------------------------------------------ registration

def test_c_registered_in_language_tables():
    from spindlebox.extract.base import ALL_LANGS, EXT_MAP
    assert EXT_MAP[".c"] == "c"
    assert EXT_MAP[".h"] == "c"
    assert "c" in ALL_LANGS
    assert profile_for("c").walker


def test_no_handwritten_extractor_module():
    import spindlebox.extract as pkg
    assert not (Path(pkg.__file__).parent / "c_lang.py").exists()


# ------------------------------------------------------------ declarations

def test_every_definition_is_found(idx):
    names = sorted(i.name for i in idx.items)
    assert names == [
        "apply_bytes", "area", "average_len", "count_words", "describe",
        "home", "main", "read_lines", "reset", "split_words", "sum_all",
    ]
    assert all(i.kind == "function" and i.language == "c" for i in idx.items)


def test_header_prototypes_are_not_items(idx):
    assert not [i for i in idx.items if i.file.endswith(".h")]


def test_span_covers_the_whole_definition(idx):
    item = by_addr(idx, "textkit.count_words")
    lines = (FIXTURE / "textkit.c").read_text().splitlines()
    start, end = item.span
    assert lines[start - 1].startswith("int count_words")
    assert lines[end - 1] == "}"


# ------------------------------------------------------------ the hook's job

def test_pointer_returning_function_keeps_its_name_and_type(idx):
    item = by_addr(idx, "textkit.read_lines")
    assert item.signature.returns_raw == "char *"
    assert item.signature.returns_norm == "str"


def test_double_pointer_return(idx):
    item = by_addr(idx, "textkit.split_words")
    assert item.signature.returns_raw == "char **"
    assert item.signature.returns_norm == "list<str>"


def test_parameters_come_off_the_nested_function_declarator(idx):
    item = by_addr(idx, "textkit.split_words")
    assert [(p.name, p.raw_type, p.norm_type) for p in item.signature.params] == [
        ("text", "char *", "str"),
        ("out_count", "int *", "list<i64>"),
    ]


def test_void_parameter_list_is_empty(idx):
    assert by_addr(idx, "textkit.reset").signature.params == []
    assert by_addr(idx, "textkit.reset").signature.returns_norm == "unit"


def test_variadic_parameter(idx):
    item = by_addr(idx, "textkit.sum_all")
    variadic = [p for p in item.signature.params if p.kind == "variadic"]
    assert variadic and variadic[0].norm_type == "list<any>"


def test_unnamed_parameter_falls_back_to_positional_name():
    decls = parse_c("int width_of(int) { return 3; }")
    assert [(p.name, p.raw_type) for p in decls[0].params] == [("arg0", "int")]


def test_function_returning_function_pointer_names_the_inner_declarator():
    # `int (*get_cb(void))(int)` — the outer function_declarator belongs to the
    # returned pointer, so the name must be found from the identifier upwards.
    decls = parse_c("int (*get_cb(void))(int) { return 0; }")
    assert [d.name for d in decls] == ["get_cb"]
    assert decls[0].params == []


def test_function_pointer_parameter_is_named_but_untypable(idx):
    # core-1 has `fn` but no way to say "fn with this signature"; the raw
    # spelling is kept and the normalized type degrades to `any` rather than lie.
    item = by_addr(idx, "textkit.apply_bytes")
    fn_param = item.signature.params[1]
    assert fn_param.name == "fn"
    assert fn_param.raw_type == "int (*)(int)"
    assert fn_param.norm_type == "any"


# ------------------------------------------------------------------- types

def test_struct_pointer_parameter(idx):
    item = by_addr(idx, "textkit.average_len")
    param = item.signature.params[0]
    assert param.raw_type == "struct Buffer *"
    assert param.norm_type == "list<obj:Buffer>"   # a C pointer is 0..n of T
    assert item.signature.returns_norm == "f64"


def test_c_type_table():
    assert normalize("int", "c") == "i64"
    assert normalize("unsigned long", "c") == "i64"
    assert normalize("double", "c") == "f64"
    assert normalize("void", "c") == "unit"
    assert normalize("void *", "c") == "any"
    assert normalize("_Bool", "c") == "bool"
    assert normalize("char *", "c") == "str"
    assert normalize("char **", "c") == "list<str>"
    assert normalize("unsigned char *", "c") == "bytes"
    assert normalize("struct Rect", "c") == "obj:Rect"
    assert normalize("const struct Rect *", "c") == "list<obj:Rect>"
    assert normalize("enum Mode", "c") == "obj:Mode"
    assert normalize("FILE *", "c") == "obj:FILE"
    # implicit int: a definition with no type specifier is C89's `int`
    assert normalize(None, "c") == "i64"


def test_ghidra_spellings_normalize():
    # the decompiler's own type vocabulary, so decompiled trees index cleanly
    for spelling in ("undefined4", "uint", "ushort", "ulong", "byte", "dword", "longlong"):
        assert normalize(spelling, "c") == "i64", spelling
    assert normalize("code *", "c") == "fn"
    assert normalize("undefined *", "c") == "any"
    assert normalize("float10", "c") == "f64"


def test_strip_prefixes_is_opt_in_and_leaves_other_languages_alone():
    assert normalize("String", "java") == "str"
    assert normalize("const", "java") == "obj:const"


def test_cross_language_signature_class(idx):
    # C's `char *read_lines(const char *)` is the same shape as Java's readLines
    assert by_addr(idx, "textkit.read_lines").sig_class == "sig:str->str"


# --------------------------------------------------------- deps and state

def test_includes_become_imports_and_external_packages(idx):
    item = by_addr(idx, "textkit.read_lines")
    assert item.deps.imports == ["stdio.h", "stdlib.h", "string.h", "textkit.h"]
    assert item.deps.external_packages == []   # all stdlib or local


def test_getenv_is_an_env_dependency(idx):
    assert by_addr(idx, "textkit.home").deps.env_vars == ["APP_HOME"]


def test_call_resolution_within_and_across_files(idx):
    assert "textkit.count_words" in by_addr(idx, "textkit.split_words").deps.calls
    assert "textkit.count_words" in by_addr(idx, "shapes.main").deps.calls
    assert "shapes.area" in by_addr(idx, "shapes.main").deps.calls
    # libc is not in the index and must stay distinguishable from an ambiguity
    assert "external:printf" in by_addr(idx, "shapes.main").deps.calls


def test_file_scope_state_is_the_c_analogue_of_capture(idx):
    assert by_addr(idx, "textkit.reset").state_capture == "mutates_captured"
    assert by_addr(idx, "textkit.read_lines").state_capture == "mutates_captured"
    assert by_addr(idx, "textkit.average_len").state_capture == "reads_captured"
    # touches only its own locals, parameters and callees
    assert by_addr(idx, "textkit.count_words").state_capture == "pure"
    assert by_addr(idx, "shapes.area").state_capture == "pure"
    assert by_addr(idx, "textkit.apply_bytes").state_capture == "pure"


def test_a_global_read_into_a_local_still_counts_as_a_write_to_that_global():
    # the failure mode a naive `declaration` walk creates: `n = g` makes `g`
    # look locally declared, and the later write to it disappears
    decls = parse_c("static int g;\nvoid f(void) { int n = g; g = n + 1; }")
    assert decls[0].state_capture == "mutates_captured"


def test_doc_comment(idx):
    assert by_addr(idx, "textkit.read_lines").doc == \
        "read_lines slurps a whole file into one heap buffer."


def test_static_function_is_still_a_function():
    decls = parse_c("/* helper. */\nstatic unsigned int tally(int n) { return n; }")
    assert decls[0].name == "tally"
    assert decls[0].returns_raw == "unsigned int"
    assert decls[0].doc == "helper."


# ------------------------------------------------------------- coverage gate

def test_profile_coverage_is_clean():
    from spindlebox import reporting
    stack = reporting.list_stacks()["profile-coverage"]
    ctx = reporting.run_stack(stack, {"format": "json"})
    import json
    rows = {r["language"]: r for r in json.loads(ctx["output"])["rows"]}
    assert rows["c"]["missing"] == "—", rows["c"]
    assert rows["c"]["fixture_files"] >= 3


# ------------------------------------------------------- decompiler output

# exactly what scripts/ghidra/ExportDecomp.java writes: a three-line provenance
# header, then Ghidra's own output, which puts a blank line either side of the
# signature
GHIDRA_FUNCTION = """\
/* FUN_00401230 @ 0x00401230  segment text */
/* signature: void __fastcall FUN_00401230(int, undefined4 *) */
/* convention: __fastcall  frame 4 bytes */

/* WARNING: Globals starting with '_' overlap smaller symbols at the same address */

void __fastcall FUN_00401230(int param_1,undefined4 *param_2)

{
  byte bVar1;
  uint uVar2;
  undefined4 uVar4;
  char *pcVar5;
  undefined auStack_40 [32];
  int local_20;

  uVar2 = DAT_00518a40;
  if (param_1 == 0) {
    return;
  }
  bVar1 = *(byte *)(param_1 + 8);
  if ((bVar1 & 4) != 0) {
    DAT_00518a40 = uVar2 + 1;
    FUN_00402ab0(param_1,&local_20);
  }
  uVar4 = FUN_004019f0();
  pcVar5 = (char *)FUN_00403110(uVar4,auStack_40);
  if (pcVar5 != (char *)0x0) {
    (*(code *)PTR_LAB_005190a4)(pcVar5);
  }
  *param_2 = uVar4;
  return;
}
"""


def test_decompiler_output_parses():
    decls = parse_c(GHIDRA_FUNCTION, "src/text/FUN_00401230.c")
    assert [d.name for d in decls] == ["FUN_00401230"]
    d = decls[0]
    assert d.returns_raw == "void"
    assert [(p.name, p.raw_type) for p in d.params] == [
        ("param_1", "int"), ("param_2", "undefined4 *"),
    ]
    # no doc: the decompiler separates its comment block from the signature with
    # a blank line, so nothing is attached. Name, signature and convention are
    # carried by the exporter's graph.json, not recovered from the comment.
    assert d.doc is None
    # writes DAT_00518a40, which is neither local nor callee
    assert d.state_capture == "mutates_captured"


def test_decompiler_indirect_call_is_not_a_named_edge():
    # `(*(code *)PTR_LAB_005190a4)(pcVar5)` has no statically known target;
    # inventing one would be worse than recording no edge
    calls = parse_c(GHIDRA_FUNCTION, "src/text/FUN_00401230.c")[0].calls
    assert calls == ["FUN_00402ab0", "FUN_004019f0", "FUN_00403110"]


@pytest.mark.parametrize("convention", [
    "__cdecl", "__stdcall", "__fastcall", "__thiscall", "__vectorcall", "__clrcall",
])
def test_pointer_return_with_a_calling_convention(convention):
    # `undefined4 * __cdecl f(x)` is a multiplication to tree-sitter-c, because
    # `undefined4` is not one of its primitive-type keywords: the definition
    # collapses into an ERROR node and the function disappears. Ghidra spells
    # nearly every function that way.
    src = f"undefined4 * {convention} f(short a)\n\n{{\n  return (undefined4 *)0x0;\n}}\n"
    decls = parse_c(src)
    assert [(d.name, d.returns_raw) for d in decls] == [("f", "undefined4 *")]


def test_calling_convention_fixup_preserves_every_offset():
    # the fixup blanks in place; if it ever shifted a byte, every span in the
    # file would point at the wrong lines
    src = ("/* head */\n"
           "undefined4 * __cdecl f(short a)\n\n{\n  return (undefined4 *)0x0;\n}\n")
    d = parse_c(src)[0]
    assert (d.start_line, d.end_line) == (2, 6)
    assert src.splitlines()[d.start_line - 1].startswith("undefined4 * __cdecl f")


def test_calling_convention_is_untouched_where_it_parses():
    d = parse_c("void __fastcall f(short a)\n\n{\n  return;\n}\n")[0]
    assert d.name == "f" and d.returns_raw == "void"
    assert "__fastcall" in d.body_text


def test_a_length_changing_source_hook_is_refused(monkeypatch):
    from spindlebox.extract import profile_lang
    monkeypatch.setitem(profile_lang.HOOKS, "c_ms_call_modifier", lambda s: "")
    assert parse_c("int f(void) { return 1; }")[0].name == "f"


def test_label_that_ends_a_block_does_not_lose_the_function():
    # Ghidra emits `LAB_x:` immediately before a `}` when a jump target lands on
    # the end of a block. It is not valid C, tree-sitter-c rejects it, and the
    # whole definition becomes an ERROR node — the function disappears silently.
    src = ("void f(int a)\n\n{\n  if (a != 0) {\n    goto LAB_004b65de;\n  }\n"
           "  a = a + 1;\nLAB_004b65de:\n}\n")
    decls = parse_c(src)
    assert [d.name for d in decls] == ["f"]
    assert (decls[0].start_line, decls[0].end_line) == (1, 9)


def test_a_switch_default_is_not_turned_into_a_statement():
    src = ("int f(int a)\n\n{\n  switch (a) {\n  case 1:\n    return 2;\n  default:\n  }\n"
           "  return 0;\n}\n")
    decls = parse_c(src)
    assert [d.name for d in decls] == ["f"]
    assert "default:" in decls[0].body_text


def test_both_fixups_stay_reachable_by_their_own_names():
    # the composite is what the profile names; neither piece was removed
    from spindlebox.extract.profile_lang import HOOKS
    assert set(HOOKS) >= {"c_ms_call_modifier", "c_dangling_label", "c_decompiler_fixups"}
    assert profile_for("c").raw["source_hook"] == "c_decompiler_fixups"
