import shutil
import subprocess
from pathlib import Path

import pytest

from spindlebox.extract import build_index
from spindlebox.generate import BACKENDS, GenOptions

FIXTURE = Path(__file__).parent / "fixtures" / "miniproj_mixed"


@pytest.fixture(scope="module")
def files():
    idx = build_index(FIXTURE, project_name="miniproj_mixed")
    backend = BACKENDS["rust"]()
    return {f.relpath: f.content for f in backend.generate(idx, GenOptions())}


def test_emits_crate(files):
    assert "Cargo.toml" in files
    assert "src/lib.rs" in files
    assert 'name = "miniproj_mixed"' in files["Cargo.toml"]


def test_ctx_struct_from_schema(files):
    lib = files["src/lib.rs"]
    assert "pub struct Ctx" in lib
    assert "pub path: Option<String>" in lib
    assert "#[derive(Default, Debug)]" in lib


def test_ctx_op_and_error(files):
    lib = files["src/lib.rs"]
    assert "pub type CtxOp = Box<dyn FnMut(&mut Ctx) -> Result<(), OpError>>;" in lib
    assert "MissingCtxKey" in lib


def test_sig_aliases(files):
    lib = files["src/lib.rs"]
    assert "// sig:str->list<str>" in lib
    assert "Box<dyn Fn(String) -> Vec<String>>" in lib


def test_skeletons_with_todo(files):
    lib = files["src/lib.rs"]
    assert "todo!()" in lib
    assert "pub fn add(a: i64, b: i64) -> i64" in lib
    assert "pub fn read_lines(path: String) -> Vec<String>" in lib


def test_ctx_wrappers(files):
    lib = files["src/lib.rs"]
    assert "pub fn add_op() -> crate::CtxOp" in lib
    assert 'ok_or(crate::OpError::MissingCtxKey("a"))?' in lib


def test_op_arrays(files):
    lib = files["src/lib.rs"]
    assert "Vec<crate::CtxOp>" in lib
    assert "pub fn ops_" in lib


def test_method_receiver_folded(files):
    lib = files["src/lib.rs"]
    assert "recv: &mut serde_json::Value" in lib


@pytest.mark.skipif(shutil.which("cargo") is None, reason="cargo not installed")
def test_cargo_check(files, tmp_path):
    for rel, content in files.items():
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    proc = subprocess.run(
        ["cargo", "check", "--quiet"], cwd=tmp_path, capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr


def test_param_named_ctx_does_not_shadow(files):
    """Issue #1: a source param named 'ctx' must not shadow the wrapper's Ctx binding."""
    lib = files["src/lib.rs"]
    assert "|__ctx: &mut crate::Ctx|" in lib
    assert "pub fn wrap_op() -> crate::CtxOp" in lib
    # the return-key write must target the closure binding, never a shadowed param
    assert "__ctx.wrap_result = Some(result);" in lib
    assert "\n                ctx.wrap_result" not in lib


def test_fn_named_ctx_called_via_self_path(files):
    """Drill finding: a function NAMED __ctx must be call-qualified so the wrapper's
    __ctx binding cannot shadow it (rustc E0618)."""
    lib = files["src/lib.rs"]
    assert "pub fn __ctx(x: i64) -> i64" in lib
    assert "let result = self::__ctx(x);" in lib


def test_blank_identifier_is_safe(files):
    """A param/ctx key named '_' (Go/rust blank identifier, memchr/cobra #4/#5)
    must never emit a bare reserved '_' in Rust."""
    lib = files["src/lib.rs"]
    assert "pub _:" not in lib
    assert "\n    _ " not in lib and "let _ =" not in lib.replace("let _ = result;", "")


def test_no_malformed_type_aliases(files):
    """No generated code line (comments excluded) may contain a stray core-1
    fragment like 'obj:' in a type position (memchr #6)."""
    lib = files["src/lib.rs"]
    for line in lib.splitlines():
        code = line.split("//", 1)[0]  # sig_class strings legitimately live in comments
        assert "obj:" not in code, f"stray core-1 fragment in code: {line}"
        if code.strip().startswith("pub type Sig"):
            assert code.rstrip().endswith(";"), f"malformed alias: {line}"


def test_mod_seg_prelude_and_collisions():
    """Module segments must not shadow prelude types or collide when distinct
    source names sanitize identically (memchr #6 deeper layer: E0573/E0428)."""
    from spindlebox.generate.rust_backend import _mod_seg
    # plain identifiers pass through unchanged
    assert _mod_seg("io") == "io"
    assert _mod_seg("Reader") == "Reader"
    # prelude type names must be escaped (no `pub mod Vec` shadowing `Vec<..>`)
    assert _mod_seg("Vec") != "Vec"
    assert _mod_seg("String") != "String"
    # distinct exotic names that sanitize alike get distinct segments
    a, b = _mod_seg("&mut T"), _mod_seg("*mut T")
    assert a != b
    # deterministic
    assert _mod_seg("&mut T") == a


def test_param_list_identifiers_unique(files):
    """Two blank params ('_','_') must not both become 'blank' (serde_json #7, E0415)."""
    import re
    lib = files["src/lib.rs"]
    for m in re.finditer(r"pub fn \w+\(([^)]*)\)", lib):
        names = [p.split(":")[0].strip() for p in m.group(1).split(",") if ":" in p]
        assert len(names) == len(set(names)), f"duplicate param name in: {m.group(0)}"


def test_rust_reserved_keywords_escaped(files):
    """Params named after Rust reserved-for-future keywords (pydantic T3) must be
    r#-escaped, not emitted bare."""
    lib = files["src/lib.rs"]
    assert "pub fn reserved(" in lib
    for kw in ("final", "override", "macro"):
        assert f" {kw}:" not in lib, f"bare reserved keyword {kw} in a param"
        assert f"r#{kw}" in lib


def test_mod_seg_never_starts_with_digit():
    """A numeric-derived group name must not yield a digit-leading module ident
    (pydantic T3 #9: 'found 1_0_1_85518c')."""
    from spindlebox.generate.rust_backend import _mod_seg
    for name in ("1.0.1", "123", "0abc", "_1_"):
        seg = _mod_seg(name)
        assert not seg[0].isdigit(), f"{name} -> {seg} starts with a digit"


def test_ctx_struct_fields_unique(files):
    """No two Ctx struct fields may share an identifier (pydantic T3 #E0124)."""
    import re
    lib = files["src/lib.rs"]
    m = re.search(r"pub struct Ctx \{(.*?)\n\}", lib, re.S)
    fields = re.findall(r"pub (\S+):", m.group(1))
    assert len(fields) == len(set(fields)), "duplicate Ctx field"


@pytest.mark.skipif(shutil.which("cargo") is None, reason="cargo not installed")
def test_cargo_check_java_fixture(tmp_path):
    """Rust generated from the profile-driven Java index must compile."""
    idx = build_index(
        Path(__file__).parent / "fixtures" / "miniproj_java",
        project_name="miniproj_java", langs=["java"],
    )
    backend = BACKENDS["rust"]()
    for f in backend.generate(idx, GenOptions()):
        out = tmp_path / f.relpath
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(f.content)
    proc = subprocess.run(
        ["cargo", "check", "--quiet"], cwd=tmp_path, capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr
