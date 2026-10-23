"""Data structures are SHOWN: indexed into a language-neutral `types` section (gx/datastructs)."""
from __future__ import annotations

import pytest
from conftest import EXPECTED, LANGS, MODEL, OBJ_REF, expected, model_types


def test_types_section_shape(indexes):
    """DS-SHAPE: every `types` entry carries name, kind, type_params and its members."""
    for lang, idx in indexes.items():
        types = idx.get("types")
        assert isinstance(types, list) and types, f"{lang}: index has no `types` section"
        for t in types:
            assert {"name", "kind", "type_params"} <= set(t), f"{lang}: {t}"
            assert t["kind"] in ("record", "variant"), f"{lang}: {t}"
            members = t["fields"] if t["kind"] == "record" else t["variants"]
            assert isinstance(members, list), f"{lang}: {t}"


@pytest.mark.parametrize("lang", LANGS)
def test_model_types_indexed(indexes, lang):
    """DS-PY / DS-GO / DS-RS / DS-TS / DS-JV: all seven model types, exactly."""
    assert model_types(indexes[lang]) == expected(lang)


def test_parity_across_languages(indexes):
    """DS-PARITY: one model, one normalized shape, whichever language declared it."""
    shapes = {lang: model_types(idx) for lang, idx in indexes.items()}
    for lang in ("go", "rust", "java"):
        assert shapes[lang] == shapes["python"], lang
    widened = {k: v.replace(":f64", ":i64") for k, v in shapes["typescript"].items()}
    assert widened == shapes["python"]


@pytest.mark.parametrize("lang", LANGS)
def test_references_resolve_and_nothing_is_erased(indexes, lang):
    """DS-REF: each obj:<Name> in a model type is itself in `types`; no field is `any`."""
    idx = indexes[lang]
    names = {t["name"] for t in idx.get("types", [])}
    shapes = model_types(idx)
    assert set(shapes) == set(MODEL), f"{lang}: missing {set(MODEL) - set(shapes)}"
    for name, form in shapes.items():
        for ref in OBJ_REF.findall(form):
            assert ref in names, f"{lang}: {name} refers to obj:{ref}, which is not indexed"
        assert ":any" not in form and "<any" not in form, f"{lang}: {form}"


@pytest.mark.parametrize("lang", LANGS)
def test_function_over_the_model_uses_its_types(indexes, lang):
    """DS-SIG: total(order) is obj:Order -> obj:Money in every language."""
    totals = [i for i in indexes[lang]["items"] if i["address"].rsplit(".", 1)[-1] == "total"]
    assert len(totals) == 1, f"{lang}: {[i['address'] for i in totals]}"
    sig = totals[0]["signature"]
    assert [p["norm_type"] for p in sig["params"] if p["kind"] != "receiver"] == ["obj:Order"]
    assert sig["returns"]["norm_type"] == "obj:Money"


def test_expected_model_is_complete():
    """The register's expected forms cover exactly the seven model types."""
    assert set(EXPECTED) == set(MODEL)
