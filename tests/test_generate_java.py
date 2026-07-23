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
])
def test_javac_check(project, tmp_path):
    proc = _javac(gen(project), tmp_path)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.skipif(shutil.which("javac") is None, reason="javac not installed")
def test_javac_check_java_roundtrip(tmp_path):
    """Full circle: Java source → SPI → Java skeleton that compiles."""
    proc = _javac(gen("miniproj_java", langs=["java"]), tmp_path)
    assert proc.returncode == 0, proc.stderr
