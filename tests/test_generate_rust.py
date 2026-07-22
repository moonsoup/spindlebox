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
