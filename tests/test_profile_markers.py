"""Builtins and entry points come from language profiles, not from `gaps` (#38).

`gaps` used to decide both with Python knowledge: a Python builtins table, and
the names ``__init__``/``__main__``/``setup`` with the prefixes
``cmd_``/``test_``/``handle_``. Every other language got false findings. Now:

- profiles declare ``builtins`` (marked ``builtin:<name>`` on the call),
  ``stdlib_calls`` (left ``external:`` but recorded on ``deps.stdlib_calls``)
  and ``entry_points`` (stamped on the item as ``entry_point: <reason>``);
- extraction records which markers it wrote in the index's ``project.markers``;
- `gaps` reads the markers, and keeps its old heuristics only for indexes
  that predate them;
- a profile's ``external_imports`` rule may name its import ``separators``,
  so ``::`` and ``/`` paths can be described as data.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spindlebox import depmap
from spindlebox.extract import build_index
from spindlebox.extract.profile_registry import all_profiles
from spindlebox.gaps import find_gaps
from spindlebox.schema import ScaIndex

FIXTURE = Path(__file__).parent / "fixtures" / "miniproj_markers"


def _index(lang: str) -> ScaIndex:
    return build_index(FIXTURE / lang, project_name=f"markers_{lang}", langs=[lang])


def _named(idx: ScaIndex, gaps: list[dict], kind: str) -> set[str]:
    name_of = {it.address: it.name for it in idx.items}
    return {name_of[g["address"]] for g in gaps if g["kind"] == kind}


def _unresolved(gaps: list[dict]) -> set[str]:
    return {g["detail"] for g in gaps if g["kind"] == "unresolvable_call"}


def _legacy(idx: ScaIndex) -> ScaIndex:
    """The same index as a build from before the markers existed would have written it."""
    d = idx.to_dict()
    d["project"].pop("markers", None)
    for item in d["items"]:
        item.pop("entry_point", None)
        item["deps"].pop("stdlib_calls", None)
        item["deps"]["calls"] = [
            "external:" + c[len("builtin:"):] if c.startswith("builtin:") else c
            for c in item["deps"]["calls"]]
    return ScaIndex.from_dict(json.loads(json.dumps(d)))


# ------------------------------------------------------------------ builtins

def test_go_builtins_are_not_unresolvable():
    gaps = find_gaps(_index("go"))
    assert _unresolved(gaps) == {"frobnicate_typo"}


def test_c_libc_calls_are_not_unresolvable():
    """The issue's repro: `printf`, `malloc` in C were reported as unresolvable."""
    gaps = find_gaps(_index("c"))
    assert _unresolved(gaps) == {"frobnicate_typo"}


def test_c_libc_calls_stay_external_and_are_recorded_as_stdlib():
    idx = _index("c")
    main = next(it for it in idx.items if it.name == "main")
    # libc lives outside the project: the call edge stays `external:`
    assert "external:printf" in main.deps.calls
    assert set(main.deps.stdlib_calls) == {"free", "malloc", "printf", "strlen"}


def test_python_builtins_still_not_unresolvable():
    gaps = find_gaps(_index("python"))
    assert _unresolved(gaps) == {"frobnicate_typo"}


def test_every_profile_declares_its_runtime_names():
    """A profile whose call extractor can emit unknown names declares what its runtime
    provides (an empty list is a declaration), so `gaps` has data instead of a guess."""
    for prof in all_profiles().values():
        if prof.calls.get("known_only"):
            continue
        assert "builtins" in prof.raw or "stdlib_calls" in prof.raw, prof.language


# ------------------------------------------------------------- entry points

def test_every_profile_declares_entry_points():
    for prof in all_profiles().values():
        rule = prof.raw.get("entry_points")
        assert isinstance(rule, dict) and rule.get("names"), prof.language


def test_extraction_stamps_entry_point_reasons():
    go = {it.name: it.entry_point for it in _index("go").items}
    assert go["main"] == "name:main"
    assert go["init"] == "name:init"
    assert go["TestRuns"] is not None
    assert go["setup"] is None and go["cmd_run"] is None and go["handle_event"] is None
    py = {it.name: it.entry_point for it in _index("python").items}
    assert py["main"] == "name:main"
    assert py["setup"] == "name:setup"
    assert py["cmd_run"] == "prefix:cmd_"
    assert py["handle_event"] == "prefix:handle_"
    assert py["island"] is None


def test_index_records_the_markers_it_wrote():
    idx = _index("go")
    assert {"builtin_calls", "entry_points", "stdlib_calls"} <= set(idx.markers)
    round_trip = ScaIndex.from_dict(json.loads(json.dumps(idx.to_dict())))
    assert round_trip.markers == idx.markers
    assert {it.name: it.entry_point for it in round_trip.items} == \
        {it.name: it.entry_point for it in idx.items}


def test_go_entry_points_follow_go_conventions():
    idx = _index("go")
    dead = _named(idx, find_gaps(idx), "dead_item")
    # Go's own entry points are live; Python's spellings mean nothing in Go
    assert dead == {"setup", "cmd_run", "handle_event"}


def test_c_setup_is_dead():
    idx = _index("c")
    assert _named(idx, find_gaps(idx), "dead_item") == {"setup"}


def test_python_keeps_its_conventions():
    idx = _index("python")
    assert _named(idx, find_gaps(idx), "dead_item") == {"island"}


def test_gaps_trusts_the_entry_point_marker_over_the_name():
    """With markers present, a name alone never makes an entry point."""
    idx = _index("python")
    for it in idx.items:
        if it.name == "setup":
            it.entry_point = None
    assert "setup" in _named(idx, find_gaps(idx), "dead_item")


# ----------------------------------------------------------- legacy indexes

def test_legacy_index_falls_back_to_the_old_entry_point_heuristic():
    idx = _legacy(_index("go"))
    assert idx.markers == []
    assert all(it.entry_point is None for it in idx.items)
    # the pre-#38 behaviour exactly: the Python-flavoured names count everywhere
    assert _named(idx, find_gaps(idx), "dead_item") == {"init"}


def test_legacy_index_still_recognises_builtins():
    """An index built before extraction marked builtins has `external:len`; `gaps`
    re-derives the marker from profile data instead of reporting it."""
    for lang in ("python", "go", "c"):
        idx = _legacy(_index(lang))
        assert _unresolved(find_gaps(idx)) == {"frobnicate_typo"}, lang


def test_marker_free_index_serializes_exactly_as_before():
    idx = _legacy(_index("go"))
    d = idx.to_dict()
    assert "markers" not in d and "markers" not in d["project"]
    for item in d["items"]:
        assert "entry_point" not in item
        assert "stdlib_calls" not in item["deps"]


# ---------------------------------------------------------- import roots

@pytest.fixture
def scoped_lang():
    lang = "markers_scoped_test_lang"
    depmap.register_deps(lang, [], {"separators": ["::"], "stdlib_roots": ["core"],
                                    "drop_last_segment": True})
    yield lang
    depmap._PROFILE_ENV.pop(lang, None)
    depmap._PROFILE_IMPORTS.pop(lang, None)


def test_profile_import_rule_can_split_on_double_colon(scoped_lang):
    got = depmap.external_packages(
        ["core::fmt::Write", "acme::widgets::Gear", "local::thing"], scoped_lang, {"local"})
    assert got == ["acme::widgets"]


def test_profile_import_rule_defaults_to_dot():
    lang = "markers_dotted_test_lang"
    depmap.register_deps(lang, [], {"stdlib_roots": ["core"], "drop_last_segment": True})
    try:
        assert depmap.external_packages(["core.fmt", "acme.widgets.Gear"], lang, set()) \
            == ["acme.widgets"]
    finally:
        depmap._PROFILE_ENV.pop(lang, None)
        depmap._PROFILE_IMPORTS.pop(lang, None)


def test_import_root_splits_every_separator():
    assert depmap.import_root("acme::widgets::Gear") == "acme"
    assert depmap.import_root("acme/widgets") == "acme"
    assert depmap.import_root("acme.widgets") == "acme"


def test_gaps_import_roots_understand_double_colon():
    idx = _index("python")
    main = next(it for it in idx.items if it.name == "main")
    main.deps.imports = ["frobnicate_typo::Thing"]
    assert "frobnicate_typo" not in _unresolved(find_gaps(idx))
