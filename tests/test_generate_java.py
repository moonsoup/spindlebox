"""Java output backend — defined entirely by generate/emit_profiles/java.json."""

import shutil
import subprocess
from pathlib import Path

import pytest

from spindlebox.extract import build_index
from spindlebox.generate import BACKENDS, GenOptions

FIXTURES = Path(__file__).parent / "fixtures"


def gen(project, langs=None):
    idx = build_index(FIXTURES / project, project_name=project, langs=langs)
    return {f.relpath: f.content for f in BACKENDS["java"]().generate(idx, GenOptions())}


@pytest.fixture(scope="module")
def files():
    return gen("miniproj_mixed")


def test_single_class_file(files):
    assert list(files) == ["Miniproj_mixed.java"]
    assert "public class Miniproj_mixed {" in files["Miniproj_mixed.java"]


def test_ctx_class_and_op_interface(files):
    src = files["Miniproj_mixed.java"]
    assert "public static class Ctx {" in src
    assert "public interface CtxOp { void apply(Ctx ctx); }" in src
    assert "public String path;" in src


def test_skeletons_throw_todo(files):
    src = files["Miniproj_mixed.java"]
    assert 'throw new UnsupportedOperationException("TODO");' in src


def test_cross_language_types(files):
    src = files["Miniproj_mixed.java"]
    assert "java.util.List<String> read_lines(String path)" in src


def _javac(files, tmp_path):
    for rel, content in files.items():
        (tmp_path / rel).write_text(content)
    name = next(iter(files))
    return subprocess.run(
        ["javac", "-encoding", "UTF-8", "-d", str(tmp_path / "out"), name],
        cwd=tmp_path, capture_output=True, text=True,
    )


@pytest.mark.skipif(shutil.which("javac") is None, reason="javac not installed")
@pytest.mark.parametrize("project", [
    "miniproj_mixed", "miniproj_py", "miniproj_go", "miniproj_rust", "miniproj_java",
    "miniproj_edge",
])
def test_javac_check(project, tmp_path):
    proc = _javac(gen(project), tmp_path)
    assert proc.returncode == 0, proc.stderr


def test_result_param_binding_disambiguated():
    """harness finding #11 (flask): a source param named 'result' redeclared the
    wrapper's local in Java (no let-shadowing)."""
    src = gen("miniproj_edge")["Miniproj_edge.java"]
    assert "var result_2 = Miniproj_edge.edge.process(result);" in src


def test_object_member_names_escaped():
    """harness finding #12 (click): a static 'clone()' illegally hides Object.clone()."""
    src = gen("miniproj_edge")["Miniproj_edge.java"]
    assert "public static String clone_()" in src
    assert "public static String toString_(" in src
    assert "public static String clone()" not in src


@pytest.mark.skipif(shutil.which("javac") is None, reason="javac not installed")
def test_javac_check_java_roundtrip(tmp_path):
    """Full circle: Java source → SPI → Java skeleton that compiles."""
    proc = _javac(gen("miniproj_java", langs=["java"]), tmp_path)
    assert proc.returncode == 0, proc.stderr
