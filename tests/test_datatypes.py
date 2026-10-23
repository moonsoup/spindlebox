"""Data structures are indexed into a language-neutral ``types`` section (#44).

Before #44 the index held functions only: a user type was ``obj:<Name>`` with
nothing behind it, so a model's fields, variants and type parameters could not
be shown or compared across languages. Each language below declares the same
small model -- a record, an enum, a sum of records, a generic -- and must index
to the same canonical shape. The sealed round ``gx/datastructs`` pins the full
model; this file pins the defect and the edges around it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spindlebox.extract import INDEX_MARKERS, build_index
from spindlebox.extract.profile_registry import PROFILE_DIR
from spindlebox.schema import ScaIndex
from spindlebox.typenorm import normalize

SOURCES = {
    "python": ("model.py", '''
from dataclasses import dataclass
from enum import Enum
from typing import Generic, Optional, TypeVar

T = TypeVar("T")
READ = 1
WRITE = 2
MASK = READ | WRITE


@dataclass
class Point:
    x: int
    label: Optional[str]


class Color(Enum):
    Red = 1
    Blue = 2


@dataclass
class Dot:
    at: Point


@dataclass
class Line:
    ends: list[Point]


Shape = Dot | Line


@dataclass
class Bag(Generic[T]):
    item: T
    inner: list[Bag[T]]


def area(s: Shape, b: Bag) -> int:
    return 0
'''),
    "go": ("model.go", '''package model

type Point struct {
	x     int
	label *string
}

type Color int

const (
	Red Color = iota
	Blue
)

type Shape interface{ isShape() }

type Dot struct{ at Point }
type Line struct{ ends []Point }

func (Dot) isShape()  {}
func (Line) isShape() {}

type Bag[T any] struct {
	item  T
	inner []Bag[T]
}
'''),
    "rust": ("model.rs", '''
pub struct Point {
    pub x: i64,
    pub label: Option<String>,
}

pub enum Color {
    Red,
    Blue,
}

pub enum Shape {
    Dot { at: Point },
    Line { ends: Vec<Point> },
}

pub struct Bag<T> {
    pub item: T,
    pub inner: Vec<Bag<T>>,
}
'''),
    "typescript": ("model.ts", '''
export interface Point {
  x: number;
  label: string | null;
}

export enum Color {
  Red,
  Blue,
}

export type Shape =
  | { kind: "Dot"; at: Point }
  | { kind: "Line"; ends: Point[] };

export interface Bag<T> {
  item: T;
  inner: Bag<T>[];
}
'''),
    "java": ("Model.java", '''
import java.util.List;
import java.util.Optional;

public class Model {
    public record Point(long x, Optional<String> label) {}

    public enum Color { Red, Blue }

    public sealed interface Shape permits Dot, Line {}

    public record Dot(Point at) implements Shape {}

    public record Line(List<Point> ends) implements Shape {}

    public record Bag<T>(T item, List<Bag<T>> inner) {}
}
'''),
}

EXPECTED = {
    "Point": "record Point{x:i64,label:option<str>}",
    "Color": "variant Color{Red,Blue}",
    "Shape": "variant Shape{Dot{at:obj:Point},Line{ends:list<obj:Point>}}",
    "Bag": "record Bag<T>{item:typevar:T,inner:list<obj:Bag<typevar:T>>}",
}


def canonical(t: dict) -> str:
    tp = f"<{','.join(t['type_params'])}>" if t["type_params"] else ""
    if t["kind"] == "record":
        body = ",".join(f"{f['name']}:{f['type']}" for f in t["fields"])
    else:
        body = ",".join(
            v["name"] + ("{" + ",".join(f"{f['name']}:{f['type']}" for f in v["fields"]) + "}"
                         if v["fields"] else "")
            for v in t["variants"])
    return f"{t['kind']} {t['name']}{tp}{{{body}}}"


def _index(tmp_path: Path, lang: str) -> dict:
    name, text = SOURCES[lang]
    root = tmp_path / lang
    root.mkdir()
    (root / name).write_text(text)
    idx = build_index(root, project_name=f"dt_{lang}", langs=[lang])
    idx.save(root / "index.json")
    return json.loads((root / "index.json").read_text())


@pytest.mark.parametrize("lang", sorted(SOURCES))
def test_model_indexes_to_one_shape(tmp_path, lang):
    """The defect: no ``types`` section at all. Every language's model now
    indexes to the same canonical forms (TypeScript's one number is f64)."""
    idx = _index(tmp_path, lang)
    assert "types" in idx, f"{lang}: index has no types section"
    shapes = {t["name"]: canonical(t) for t in idx["types"] if t["name"] in EXPECTED}
    want = EXPECTED if lang != "typescript" else \
        {**EXPECTED, "Point": EXPECTED["Point"].replace("x:i64", "x:f64")}
    assert shapes == want


def test_types_survive_a_save_and_load(tmp_path):
    root = tmp_path / "py"
    root.mkdir()
    (root / "model.py").write_text(SOURCES["python"][1])
    idx = build_index(root, project_name="dt", langs=["python"])
    idx.save(root / "index.json")
    again = ScaIndex.load(root / "index.json")
    assert [t.to_dict() for t in again.types] == [t.to_dict() for t in idx.types]
    assert "types" in again.markers and "types" in INDEX_MARKERS
    box = next(t for t in again.types if t.name == "Bag")
    assert box.address == "model.Bag" and box.span[0] < box.span[1]


def test_a_bit_mask_is_not_a_sum_type(tmp_path):
    """``MASK = READ | WRITE`` is spelled like ``Shape = Dot | Line``; only the
    one whose members are records is a type."""
    names = {t["name"] for t in _index(tmp_path, "python")["types"]}
    assert "Shape" in names and "MASK" not in names


def test_an_unmatched_alternative_is_listed_not_hidden(tmp_path):
    root = tmp_path / "java"
    root.mkdir()
    (root / "S.java").write_text(
        "public class S { public sealed interface Shape permits Dot, Elsewhere {}\n"
        "public record Dot(long x) implements Shape {} }\n")
    idx = build_index(root, project_name="dt", langs=["java"])
    shape = next(t for t in idx.types if t.name == "Shape")
    assert [v["name"] for v in shape.variants] == ["Dot", "Elsewhere"]
    assert shape.unresolved == ["Elsewhere"]


def test_function_signatures_keep_their_old_normal_form(tmp_path):
    """Only declarations see type parameters, generic arguments and Go's
    pointer-as-option; signatures and their classes are unchanged."""
    from spindlebox.typenorm import normalize_decl
    assert normalize("Vec<Bag<T>>", "rust") == "list<obj:Bag>"
    assert normalize("*string", "go") == "str"
    assert normalize("T", "python") == "obj:T"
    assert normalize_decl("Vec<Bag<T>>", "rust", ["T"]) == "list<obj:Bag<typevar:T>>"
    assert normalize_decl("*string", "go") == "option<str>"
    idx = _index(tmp_path, "python")
    area = next(i for i in idx["items"] if i["address"].endswith(".area"))
    assert [p["norm_type"] for p in area["signature"]["params"]] == ["obj:Shape", "obj:Bag"]


def test_every_profile_declares_its_datatypes():
    """A language either spells its data structures, or says why it has none
    (``absent``) or why they are not read yet (``unsupported``) -- never left out."""
    from spindlebox.extract.profile_registry import datatypes_for
    for path in sorted(PROFILE_DIR.glob("*.json")):
        spec = json.loads(path.read_text()).get("datatypes")
        assert isinstance(spec, dict) and spec, f"{path.name}: no datatypes block"
    assert datatypes_for("javascript") is None and datatypes_for("c") is None
    assert datatypes_for("python") is not None
