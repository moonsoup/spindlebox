"""Functions used as values are visible to analysis (#39).

The index had `closure`/`lambda` kinds and a bare `fn` type, but nothing could
see a function used as a value:

- no extractor read decorators, annotations or attributes;
- nothing recorded "takes a callable" or "returns a callable";
- a closure's enclosing item could only be recovered from its address;
- ``f(x)`` with ``f`` a parameter resolved by name to any item called ``f``, or
  to ``external:f``;
- ``TABLE[k](x)`` was silently dropped.

Now items carry ``decorators``, ``parent``, ``takes_fn`` and ``returns_fn``, and
indirect calls are marked ``param:<name>`` and ``table:<address>``. Each is
populated for every language whose profile declares the construct; a profile
where the construct is absent says so explicitly (``{"absent": "<why>"}``),
it is never defaulted. Every fixture under ``fixtures/miniproj_meta`` spells the
same program -- ``tagged`` (decorated), ``apply(f, x)`` (calls through ``f``),
``make_adder`` (returns a nested function) and ``dispatch`` (calls through
``HANDLERS[k]``) -- as far as its language has the construct.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spindlebox.extract import build_index
from spindlebox.extract.profile_registry import (
    CONSTRUCTS,
    PROFILE_DIR,
    all_profiles,
    declared_constructs,
    meta_for,
)
from spindlebox.schema import Item, ScaIndex

FIXTURE = Path(__file__).parent / "fixtures" / "miniproj_meta"
LANGS = sorted(p.name for p in FIXTURE.iterdir() if p.is_dir())

#: What ``tagged``'s first decorator reads as, sigil stripped, per language.
DECORATOR_TEXT = {
    "python": "deco",
    "javascript": "deco",
    "typescript": "deco()",
    "java": "Deprecated",
    "rust": "inline",
    "c": "__attribute__((unused))",
}


def _index(lang: str) -> ScaIndex:
    return build_index(FIXTURE / lang, project_name=f"meta_{lang}", langs=[lang])


@pytest.fixture(scope="module")
def indexes() -> dict[str, ScaIndex]:
    return {lang: _index(lang) for lang in LANGS}


def _named(idx: ScaIndex, name: str) -> Item:
    found = [i for i in idx.items if i.name == name]
    assert len(found) == 1, f"expected one item named {name}, got {[i.address for i in found]}"
    return found[0]


# ------------------------------------------------- profiles declare every construct

def test_every_profile_declares_every_construct_explicitly():
    assert set(CONSTRUCTS) == {
        "decorators", "parent", "takes_fn", "returns_fn", "param_calls", "table_calls"}
    for path in sorted(PROFILE_DIR.glob("*.json")):
        meta = json.loads(path.read_text()).get("meta")
        assert isinstance(meta, dict), f"{path.name}: no 'meta' block"
        assert set(meta) == set(CONSTRUCTS), f"{path.name}: meta keys {sorted(meta)}"
        for construct, spec in meta.items():
            assert isinstance(spec, dict), f"{path.name}: meta.{construct} is not an object"
            if "absent" in spec:
                assert isinstance(spec["absent"], str) and spec["absent"].strip(), (
                    f"{path.name}: meta.{construct} is absent without saying why")


def test_python_declares_every_construct():
    meta = meta_for("python")
    assert set(meta) == set(CONSTRUCTS)
    assert declared_constructs("python") == list(CONSTRUCTS)


def test_every_fixture_language_has_a_profile_or_native_meta():
    assert set(LANGS) == set(all_profiles()) | {"python"}
    for lang in LANGS:
        assert set(meta_for(lang)) == set(CONSTRUCTS)


def test_an_unknown_language_declares_nothing():
    assert meta_for("cobol") == {}
    assert declared_constructs("cobol") == []


# ---------------------------------------------- populated iff declared, per language

@pytest.mark.parametrize("lang", LANGS)
def test_index_records_which_constructs_each_language_declares(indexes, lang):
    idx = indexes[lang]
    assert idx.constructs == {lang: declared_constructs(lang)}
    round_trip = ScaIndex.from_dict(json.loads(json.dumps(idx.to_dict())))
    assert round_trip.constructs == idx.constructs
    assert {"decorators", "parent", "takes_fn", "returns_fn",
            "param_calls", "table_calls"} <= set(idx.markers)


@pytest.mark.parametrize("lang", LANGS)
def test_decorators(indexes, lang):
    idx = indexes[lang]
    if "decorators" not in declared_constructs(lang):
        assert all(not i.decorators for i in idx.items)
        return
    tagged = _named(idx, "tagged")
    assert tagged.decorators and tagged.decorators[0] == DECORATOR_TEXT[lang]
    assert not _named(idx, "make_adder").decorators


@pytest.mark.parametrize("lang", LANGS)
def test_closure_parent(indexes, lang):
    idx = indexes[lang]
    if "parent" not in declared_constructs(lang):
        assert all(i.parent is None for i in idx.items)
        return
    outer = _named(idx, "make_adder")
    inner = [i for i in idx.items
             if i.span[0] > outer.span[0] and i.span[1] <= outer.span[1]]
    assert inner, "fixture must nest a function inside make_adder"
    assert all(i.parent == outer.address for i in inner)
    assert outer.parent is None
    by_address = {i.address for i in idx.items}
    assert all(i.parent in by_address for i in idx.items if i.parent is not None)


@pytest.mark.parametrize("lang", LANGS)
def test_takes_fn(indexes, lang):
    idx = indexes[lang]
    if "takes_fn" not in declared_constructs(lang):
        assert all(not i.takes_fn for i in idx.items)
        return
    assert _named(idx, "apply").takes_fn is True
    assert _named(idx, "make_adder").takes_fn is False
    assert _named(idx, "inc").takes_fn is False


@pytest.mark.parametrize("lang", LANGS)
def test_returns_fn(indexes, lang):
    idx = indexes[lang]
    if "returns_fn" not in declared_constructs(lang):
        assert all(not i.returns_fn for i in idx.items)
        return
    assert _named(idx, "make_adder").returns_fn is True
    assert _named(idx, "apply").returns_fn is False
    assert _named(idx, "inc").returns_fn is False


@pytest.mark.parametrize("lang", LANGS)
def test_param_calls(indexes, lang):
    idx = indexes[lang]
    if "param_calls" not in declared_constructs(lang):
        assert not any(c.startswith("param:") for i in idx.items for c in i.deps.calls)
        return
    apply = _named(idx, "apply")
    calls = apply.deps.calls
    assert "param:f" in calls
    assert "external:f" not in calls
    # Java's f.apply(x) used to resolve by name to the item `apply` itself
    assert apply.address not in calls


@pytest.mark.parametrize("lang", LANGS)
def test_table_calls(indexes, lang):
    idx = indexes[lang]
    if "table_calls" not in declared_constructs(lang):
        assert not any(c.startswith("table:") for i in idx.items for c in i.deps.calls)
        return
    assert "table:app.HANDLERS" in _named(idx, "dispatch").deps.calls


def test_go_table_call_through_a_literal_key(indexes):
    # `HANDLERS[k](x)` parses as a generic type conversion in Go; a literal key
    # parses as an index expression. Both are the same call through a table.
    assert "table:app.HANDLERS" in _named(indexes["go"], "dispatch_literal").deps.calls


# ------------------------------------------------------------ python specifics

def test_python_subscript_call_is_no_longer_dropped(indexes):
    idx = indexes["python"]
    assert _named(idx, "local_dispatch").deps.calls == ["table:app.local_dispatch.table"]


def test_python_table_through_the_receiver_is_addressed_on_its_class(indexes):
    assert _named(indexes["python"], "route").deps.calls == ["table:app.Router.routes"]


def test_python_decorator_text_is_the_expression(indexes):
    assert _named(indexes["python"], "static_route").decorators == ["staticmethod"]


# ------------------------------------------------------------------ the schema

def test_fields_are_omitted_when_empty_and_round_trip(indexes):
    idx = indexes["python"]
    inc = _named(idx, "inc").to_dict()
    for key in ("decorators", "parent", "takes_fn", "returns_fn"):
        assert key not in inc
    adder = _named(idx, "adder")
    d = adder.to_dict()
    assert d["parent"] == _named(idx, "make_adder").address
    assert Item.from_dict(json.loads(json.dumps(d))) == adder
    tagged = _named(idx, "tagged")
    assert Item.from_dict(json.loads(json.dumps(tagged.to_dict()))) == tagged


def test_an_index_from_before_the_fields_still_loads(indexes):
    d = indexes["python"].to_dict()
    d["project"].pop("constructs", None)
    for item in d["items"]:
        for key in ("decorators", "parent", "takes_fn", "returns_fn"):
            item.pop(key, None)
    old = ScaIndex.from_dict(json.loads(json.dumps(d)))
    assert old.constructs == {}
    assert all(not i.decorators and i.parent is None and not i.takes_fn
               and not i.returns_fn for i in old.items)
