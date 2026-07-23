"""Pipelines must COMPOSE, not just type-check (the double→triple defect).

A direct chain — stage N's return feeding stage N+1's sole required param —
was accepted by the validator but executed as two independent reads of the
initial ctx: triple(2)=6 instead of triple(double(2))=12. These tests pin the
fix at every layer: edge computation, the Python runner, the CLI, and the
generated Rust (executed, not just compiled) and Java code.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from spindlebox.dispatch import run_pipeline
from spindlebox.extract import build_index
from spindlebox.generate import BACKENDS, GenOptions
from spindlebox.schema import Pipeline
from spindlebox.validate import pipeline_edges, validate_index

FIXTURE = Path(__file__).parent / "fixtures" / "miniproj_py"


@pytest.fixture(scope="module")
def chained_idx():
    idx = build_index(FIXTURE, project_name="miniproj_py")
    dbl = idx.item_by_address("pure.double")
    tri = idx.item_by_address("pure.triple")
    pipe = Pipeline(name="chain", stages=[dbl.ordinal, tri.ordinal], checked=True)
    pipe.edges = pipeline_edges([dbl, tri])
    idx.pipelines.append(pipe)
    errors, _ = validate_index(idx)
    assert not [e for e in errors if "chain" in e]
    return idx


def test_direct_chain_gets_an_edge(chained_idx):
    dbl = chained_idx.item_by_address("pure.double")
    assert chained_idx.pipelines[-1].edges == [
        {"after": dbl.ordinal, "from_key": "double_result", "to_key": "x"}
    ]


def test_ctx_mediated_chain_needs_no_edge(chained_idx):
    rl = chained_idx.item_by_address("util.io.read_lines")
    ex = chained_idx.item_by_address("util.io.exists")
    assert pipeline_edges([rl, ex]) == []


def test_python_runner_composes(chained_idx):
    out = run_pipeline(chained_idx, FIXTURE, "chain", {"x": 2})
    assert out["double_result"] == 4
    assert out["triple_result"] == 12, "pipeline executed stages independently"


def test_runner_without_edges_recomputes(chained_idx):
    chained_idx.pipelines[-1].edges = []
    try:
        out = run_pipeline(chained_idx, FIXTURE, "chain", {"x": 2})
    finally:
        dbl = chained_idx.item_by_address("pure.double")
        tri = chained_idx.item_by_address("pure.triple")
        chained_idx.pipelines[-1].edges = pipeline_edges([dbl, tri])
    assert out["triple_result"] == 12


def _gen(idx, lang):
    return {f.relpath: f.content for f in BACKENDS[lang]().generate(idx, GenOptions())}


def test_rust_emits_edge_op_in_both_backends(chained_idx):
    from spindlebox.generate.profile_backend import load_emit_backends
    legacy = _gen(chained_idx, "rust")["src/lib.rs"]
    profiled = {f.relpath: f.content
                for f in load_emit_backends()["rust"]().generate(
                    chained_idx, GenOptions())}["src/lib.rs"]
    edge = "__ctx.x = __ctx.double_result.clone(); Ok(()) })"
    assert edge in legacy and edge in profiled
    assert legacy == profiled  # differential holds with pipelines present


@pytest.mark.skipif(shutil.which("javac") is None, reason="javac not installed")
def test_java_pipeline_with_edge_compiles(chained_idx, tmp_path):
    files = _gen(chained_idx, "java")
    src = files["Miniproj_py.java"]
    assert "__ctx.x = (Long) (Object) __ctx.double_result;" in src
    for rel, content in files.items():
        (tmp_path / rel).write_text(content)
    r = subprocess.run(["javac", "-encoding", "UTF-8", "-d", str(tmp_path / "out"),
                        *files], cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.mark.skipif(shutil.which("cargo") is None, reason="cargo not installed")
def test_generated_rust_pipeline_actually_composes(chained_idx, tmp_path):
    """The strongest proof: fill the two stub bodies, RUN the generated
    pipeline, and assert 12 — behavior, not just compilation."""
    files = _gen(chained_idx, "rust")
    lib = files["src/lib.rs"]
    lib = lib.replace(
        "pub fn double(x: i64) -> i64 {\n        todo!()\n    }",
        "pub fn double(x: i64) -> i64 {\n        x * 2\n    }")
    lib = lib.replace(
        "pub fn triple(x: i64) -> i64 {\n        todo!()\n    }",
        "pub fn triple(x: i64) -> i64 {\n        x * 3\n    }")
    assert "x * 2" in lib and "x * 3" in lib, "stub replacement failed"
    lib += """
#[cfg(test)]
mod dataflow_tests {
    #[test]
    fn pipeline_carries_data_forward() {
        let mut ctx = crate::Ctx::default();
        ctx.x = Some(2);
        for op in crate::pipeline_chain().iter_mut() {
            op(&mut ctx).unwrap();
        }
        assert_eq!(ctx.triple_result, Some(12));
    }
}
"""
    (tmp_path / "src").mkdir()
    (tmp_path / "Cargo.toml").write_text(files["Cargo.toml"])
    (tmp_path / "src" / "lib.rs").write_text(lib)
    r = subprocess.run(["cargo", "test", "--quiet"], cwd=tmp_path,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
