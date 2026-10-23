"""Data structures are REPLICATED: generated into Java and Rust, compiled, and re-indexed back
to the same shape (gx/datastructs)."""
from __future__ import annotations

import re
import shutil
import subprocess

import pytest
from conftest import LANGS, expected, generate, index_dir, model_types

TARGETS = ["java", "rust"]


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("target", TARGETS)
def test_round_trip_preserves_every_model_type(work, lang, target):
    """DS-GEN-JAVA / DS-GEN-RUST: re-indexing the generated code gives back the source shape."""
    out = generate(lang, target, work / f"rt_{lang}_{target}")
    back = index_dir(out, work / f"rt_{lang}_{target}", f"back_{lang}_{target}")
    assert model_types(back) == expected(lang)


@pytest.mark.skipif(shutil.which("javac") is None, reason="javac not installed")
@pytest.mark.parametrize("lang", LANGS)
def test_generated_java_compiles(work, lang):
    """DS-GEN-JAVA: the generated Java, model types included, compiles."""
    out = generate(lang, "java", work / f"javac_{lang}")
    sources = [str(p) for p in out.rglob("*.java")]
    assert sources, "no .java files generated"
    proc = subprocess.run(["javac", "-encoding", "UTF-8", "-d", str(work / f"javac_{lang}" / "classes"), *sources],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.skipif(shutil.which("cargo") is None, reason="cargo not installed (#27): Rust compile unverified here")
@pytest.mark.parametrize("lang", LANGS)
def test_generated_rust_compiles(work, lang):
    """DS-GEN-RUST: the generated crate, model types included, passes cargo check."""
    out = generate(lang, "rust", work / f"cargo_{lang}")
    manifest = next(out.rglob("Cargo.toml"), None)
    assert manifest is not None, "no Cargo.toml generated"
    proc = subprocess.run(["cargo", "check", "--quiet", "--offline"], cwd=manifest.parent,
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


JAVA_TOTAL = re.compile(r"\b([\w.]*Money)\s+total\s*\(\s*(?:final\s+)?([\w.]*Order)\s+\w+\s*\)")
RUST_TOTAL = re.compile(r"fn\s+total\s*\(\s*\w+\s*:\s*&?(?:mut\s+)?([\w:]*Order)\s*\)\s*->\s*([\w:]*Money)")


@pytest.mark.parametrize("lang", LANGS)
def test_generated_signatures_use_the_model_types(work, lang):
    """DS-GEN-SIG: total(Order) -> Money is generated with the model types, not an opaque stand-in."""
    java = "\n".join(p.read_text() for p in generate(lang, "java", work / f"sigj_{lang}").rglob("*.java"))
    rust = "\n".join(p.read_text() for p in generate(lang, "rust", work / f"sigr_{lang}").rglob("*.rs"))
    assert JAVA_TOTAL.search(java), "Java: no `Money total(Order ...)`"
    assert RUST_TOTAL.search(rust), "Rust: no `fn total(...: Order) -> Money`"
    for line in rust.splitlines():
        if re.search(r"fn\s+total\s*\(", line):
            assert "serde_json::Value" not in line, line
