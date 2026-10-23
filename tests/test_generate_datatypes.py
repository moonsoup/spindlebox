"""Generation replicates the index's data structures (#45).

The falsifiable check is the round trip: generate Java and Rust from an index, index
the generated code with the same indexer, and compare the declared types' shape. A
signature `total(Order) -> Money` must keep both types, not an opaque stand-in.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from spindlebox.extract import build_index
from spindlebox.generate import BACKENDS, GenOptions
from spindlebox.generate.rust_backend import rust_type
from spindlebox.typenorm import normalize

PY_MODEL = '''\
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Generic, Optional, TypeVar

T = TypeVar("T")


@dataclass
class Money:
    amount: int
    currency: str


class Status(Enum):
    Pending = "pending"
    Paid = "paid"


@dataclass
class Card:
    last4: str


@dataclass
class Cash:
    pass


Payment = Card | Cash


@dataclass
class Order:
    id: str
    status: Status
    payment: Optional[Payment]
    tags: dict[str, list[str]]


@dataclass
class Tree(Generic[T]):
    value: T
    children: list[Tree[T]]


def total(order: Order) -> Money:
    return Money(0, "EUR")
'''

JAVA_MODEL = '''\
public class Model {
    public record Money(long amount, String currency) {}

    public record Order(String id) {}

    public static Money total(Order order) { return null; }

    public Money price(Order order) { return null; }
}
'''

MODEL = ("Money", "Status", "Payment", "Order", "Tree")


def shape(index) -> dict[str, dict]:
    out = {}
    for t in index.types:
        if t.name in MODEL:
            d = t.to_dict()
            for k in ("address", "language", "file", "span"):
                d.pop(k)
            for f in d.get("fields", []):
                f.pop("raw_type", None)
            for v in d.get("variants", []):
                for f in v["fields"]:
                    f.pop("raw_type", None)
            out[t.name] = d
    return out


def project(tmp_path: Path, name: str, files: dict[str, str]) -> Path:
    root = tmp_path / name
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    return root


def generate(index, lang: str) -> dict[str, str]:
    return {f.relpath: f.content for f in BACKENDS[lang]().generate(index, GenOptions())}


@pytest.fixture(scope="module")
def py_index(tmp_path_factory):
    root = project(tmp_path_factory.mktemp("src"), "pymodel", {"model.py": PY_MODEL})
    return build_index(root, project_name="pymodel")


@pytest.mark.parametrize("lang", ["java", "rust"])
def test_round_trip_preserves_types(py_index, tmp_path, lang):
    files = generate(py_index, lang)
    back = build_index(project(tmp_path, f"back_{lang}", files), project_name="back")
    assert shape(back) == shape(py_index)
    assert set(shape(py_index)) == set(MODEL)


def test_generated_signatures_use_declared_types(py_index):
    java = generate(py_index, "java")["Pymodel.java"]
    rust = generate(py_index, "rust")["src/lib.rs"]
    assert "public static Money total(Order order)" in java
    assert "pub fn total(order: crate::Order) -> crate::Money" in rust
    assert "public sealed interface Payment permits Card, Cash {}" in java
    assert "public record Card(String last4) implements Payment {}" in java
    assert "pub enum Payment { Card { last4: String, }, Cash, }" in rust


def test_rust_parity_holds_with_types(py_index):
    """The Rust emit profile and the legacy backend still agree byte-for-byte."""
    from spindlebox.generate.profile_backend import load_emit_backends
    from spindlebox.generate.rust_backend import RustBackend
    legacy = {f.relpath: f.content for f in RustBackend().generate(py_index, GenOptions())}
    engine = load_emit_backends()["rust"]().generate(py_index, GenOptions())
    assert {f.relpath: f.content for f in engine} == legacy


def test_java_static_method_has_no_receiver(tmp_path):
    idx = build_index(project(tmp_path, "jmodel", {"Model.java": JAVA_MODEL}),
                      project_name="jmodel")
    by_name = {i.name: i for i in idx.items}
    assert by_name["total"].static and not by_name["price"].static
    assert by_name["total"].kind == by_name["price"].kind == "method"
    java = generate(idx, "java")["Jmodel.java"]
    assert re.search(r"public static Money total\(Order order\)", java)
    assert re.search(r"public static Money price\(Object recv, Order order\)", java)
    assert "pub fn total(order: crate::Order) -> crate::Money" in generate(idx, "rust")["src/lib.rs"]


def test_without_types_behaviour_is_unchanged(py_index):
    """No declared types (or an undeclared name) renders exactly as before."""
    assert rust_type("obj:Order") == "serde_json::Value"
    bare = json.loads(json.dumps(py_index.to_dict()))
    bare.pop("types", None)
    from spindlebox.schema import ScaIndex
    rust = generate(ScaIndex.from_dict(bare), "rust")["src/lib.rs"]
    assert "pub fn total(order: serde_json::Value) -> serde_json::Value" in rust
    assert "data structures" not in rust


def test_rust_std_paths_normalize():
    assert normalize("std::collections::HashMap<String, Vec<String>>", "rust") == "map<str,list<str>>"
    assert normalize("std::collections::HashSet<i64>", "rust") == "set<i64>"
    assert normalize("crate::Order", "rust") == "obj:crate::Order"  # not std: unchanged


@pytest.mark.skipif(shutil.which("javac") is None, reason="javac not installed")
def test_generated_java_compiles(py_index, tmp_path):
    src = project(tmp_path, "javac", generate(py_index, "java"))
    proc = subprocess.run(["javac", "-d", str(tmp_path / "classes"), *map(str, src.rglob("*.java"))],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
