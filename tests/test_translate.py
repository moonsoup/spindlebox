"""Body translation (#21) — the first thing here that converts code, not just shape.

The load-bearing test is `test_translated_java_matches_python`: it compiles the generated
Java, RUNS it, and compares the values to the Python originals executed in this process.
Compiling proves the syntax; only running proves the semantics, and semantics is the whole
claim.

The refusal tests matter just as much. `translate_body` returning None is the safe answer,
and each refusal below is a case where a plausible translation would have been WRONG.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

from spindlebox.extract import build_index
from spindlebox.generate import BACKENDS, GenOptions
from spindlebox.translate import translate_body

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def idx():
    return build_index(FIXTURES / "miniproj_py", project_name="miniproj_py",
                       langs=["python"], with_source=True)


def item(idx, address):
    found = idx.item_by_address(address)
    assert found is not None, address
    return found


# ------------------------------------------------------------------ capture


def test_source_is_only_captured_when_asked():
    """Off by default: --with-source roughly doubles index size and only translation
    reads it. A body stays locatable via file+span either way."""
    without = build_index(FIXTURES / "miniproj_py", project_name="miniproj_py",
                          langs=["python"])
    assert all(i.source_text is None for i in without.items)
    assert item(without, "pure.add").span  # still locatable


def test_captured_source_round_trips_through_the_schema(idx, tmp_path):
    out = tmp_path / "index.json"
    idx.save(out)
    from spindlebox.schema import ScaIndex
    assert "def add" in item(ScaIndex.load(out), "pure.add").source_text


# ------------------------------------------------------------------ accepted


@pytest.mark.parametrize("address,java,rust", [
    ("pure.add", "(a + b)", "(a + b)"),
    ("app.double", "(x * 2)", "(x * 2)"),
    ("app.triple", "(x * 3)", "(x * 3)"),
    ("pure.reserved", "((final + override) + macro)", "((final + override) + macro)"),
])
def test_arithmetic_translates(idx, address, java, rust):
    assert translate_body(item(idx, address), "java") == java
    assert translate_body(item(idx, address), "rust") == rust


def test_parameter_renames_are_applied(idx):
    """Targets escape reserved words — Python `final` becomes Java `final_` — so a body
    rendered with source spellings does not compile. The backend passes the mapping it
    actually emitted; this pins that the translator honours it.

    Found by the differential test below, not by review: the generated Java declared
    `Long final_` and the body said `final`, and only javac noticed.
    """
    reserved = item(idx, "pure.reserved")
    renamed = translate_body(reserved, "java",
                             {"final": "final_", "override": "override", "macro": "macro"})
    assert renamed == "((final_ + override) + macro)"


def test_string_concat_translates_for_java_but_not_rust(idx):
    """Java `+` on String is well-defined. Rust's is not — `String + &str` needs the
    operands in a specific order and shape, so it is refused rather than guessed."""
    wrap = item(idx, "pure.wrap")
    assert translate_body(wrap, "java") == '(("[" + ctx) + "]")'
    assert translate_body(wrap, "rust") is None


# ------------------------------------------------------------------ refused


def test_fstring_is_refused(idx):
    """pure.greet is `return f"hello {name}{punct}"` — no attempt is made."""
    assert translate_body(item(idx, "pure.greet"), "java") is None


def test_refused_without_captured_source(idx):
    """The same item is untranslatable when the body was never stored.

    Uses a copy: mutating the module-scoped index poisons every later test, which is
    exactly how this file first "proved" that add() was untranslatable while the real
    generator was translating it fine.
    """
    import copy
    add = copy.copy(item(idx, "pure.add"))
    add.source_text = None
    assert translate_body(add, "java") is None
    # the shared fixture is untouched
    assert translate_body(item(idx, "pure.add"), "java") == "(a + b)"


@pytest.mark.parametrize("body,why", [
    ("def f(a: int, b: int) -> float:\n    return a / b\n",
     "Python '/' is true division; Java and Rust integer-divide"),
    ("def f(a: int, b: int) -> bool:\n    return a < b < 3\n",
     "chained comparison has no direct equivalent"),
    ("def f(a: str, b: str) -> bool:\n    return a == b\n",
     "Java '==' on String compares identity, not value"),
    ("def f(a: float, b: float) -> float:\n    return a % b\n",
     "'%' on floats differs across targets"),
    ("def f(a: int) -> int:\n    return abs(a)\n",
     "calls are not translated"),
    ("def f(a: int) -> int:\n    x = a + 1\n    return x\n",
     "multiple statements are not translated"),
])
def test_unsafe_constructs_are_refused(tmp_path, body, why):
    """Each of these has a plausible-looking translation that would be WRONG."""
    src = tmp_path / "m.py"
    src.write_text(body)
    idx = build_index(tmp_path, project_name="p", langs=["python"], with_source=True)
    fn = next(i for i in idx.items if i.name == "f")
    assert translate_body(fn, "java") is None, why
    assert translate_body(fn, "rust") is None, why


def test_division_refusal_is_the_important_one(tmp_path):
    """Called out separately because it is the one a human would most likely get wrong:
    2/2 is 1.0 in Python and 1 in Java. Silent, and only for integer operands."""
    src = tmp_path / "m.py"
    src.write_text("def f(a: int, b: int) -> float:\n    return a / b\n")
    idx = build_index(tmp_path, project_name="p", langs=["python"], with_source=True)
    assert translate_body(next(i for i in idx.items if i.name == "f"), "java") is None


# ------------------------------------------------- differential execution (the claim)


# Only `pure` is exercised here: app.py imports util.io, which pulls in `requests`, and
# the differential test must not depend on the fixture's third-party imports being
# installed. Multiplication is covered by the unit tests above (app.double -> "(x * 2)").
_MAIN = """
public class Main {
    public static void main(String[] args) {
        System.out.println(Miniproj_py.pure.add(2L, 40L));
        System.out.println(Miniproj_py.pure.add(-5L, 5L));
        System.out.println(Miniproj_py.pure.reserved(1L, 2L, 3L));
        System.out.println(Miniproj_py.pure.wrap("mid"));
    }
}
"""


def _python_reference():
    """Run the fixture's own Python functions — the values the Java must match."""
    spec = importlib.util.spec_from_file_location(
        "_fx_pure", FIXTURES / "miniproj_py" / "pure.py")
    pure = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pure)
    return [
        str(pure.add(2, 40)),
        str(pure.add(-5, 5)),
        str(pure.reserved(1, 2, 3)),
        pure.wrap("mid"),
    ]


@pytest.mark.skipif(shutil.which("javac") is None or shutil.which("java") is None,
                    reason="javac/java not installed")
def test_translated_java_matches_python(idx, tmp_path):
    """Generate Java, compile it, run it, and compare against Python.

    This is the acceptance criterion for #21. Compiling only proves the output parses;
    matching the Python values is what makes "converts a block of code with little or no
    errors" a claim rather than an aspiration.
    """
    for f in BACKENDS["java"]().generate(idx, GenOptions()):
        (tmp_path / f.relpath).write_text(f.content)
    (tmp_path / "Main.java").write_text(_MAIN)

    compiled = subprocess.run(
        ["javac", "-encoding", "UTF-8", "-d", str(tmp_path / "out"),
         "Miniproj_py.java", "Main.java"],
        cwd=tmp_path, capture_output=True, text=True)
    assert compiled.returncode == 0, compiled.stderr

    ran = subprocess.run(["java", "-cp", str(tmp_path / "out"), "Main"],
                         cwd=tmp_path, capture_output=True, text=True)
    assert ran.returncode == 0, ran.stderr

    assert ran.stdout.split() == _python_reference()


def test_python_reference_is_actually_exercised():
    """Guard: if the fixture changed such that these return None, the differential test
    above would compare nothing and pass vacuously."""
    assert _python_reference() == ["42", "0", "6", "[mid]"]
