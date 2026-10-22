"""Functions held in data are indexed as ``fn_tables`` (#40).

Module-level dicts and lists of callables, registries filled by ``register(fn)``
or a registering decorator, and packaging entry points all hold functions, but
before #40 none of them appeared in the index: a dispatch like
``OPS[name]["fn"](ctx)`` produced no edge, so every op read as a ``dead_item``.

Each fixture under ``fixtures/miniproj_fntables`` spells a ``HANDLERS`` dict
and a ``PIPE`` list of functions; the Python one adds two registries, a
heterogeneous table, a table nothing dispatches through, and a pyproject.toml
with entry points.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spindlebox.extract import build_index, profile_registry
from spindlebox.extract.profile_registry import PROFILE_DIR
from spindlebox.gaps import find_gaps
from spindlebox.schema import ScaIndex, SchemaError
from spindlebox.validate import validate_index
from spindlebox.workflows import mine_workflows

REPO = Path(__file__).parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "miniproj_fntables"
FIELDS = {"address", "file", "span", "kind", "members", "key_type"}
OPS = "pkg.ops"


@pytest.fixture(scope="module")
def py_index() -> ScaIndex:
    return build_index(FIXTURE / "python", project_name="fntables_py", langs=["python"])


def _table(idx: ScaIndex, address: str):
    found = [t for t in idx.fn_tables if t.address == address]
    assert len(found) == 1, f"no table {address}: {[t.address for t in idx.fn_tables]}"
    return found[0]


def _line_of(rel: str, needle: str) -> int:
    lines = (FIXTURE / "python" / rel).read_text().splitlines()
    return next(n for n, line in enumerate(lines, 1) if needle in line)


# ---------------------------------------------------------------- the section

def test_fn_tables_section_has_exactly_the_issue_fields(py_index):
    doc = py_index.to_dict()
    assert "fn_tables" in doc
    assert doc["fn_tables"], "no tables serialized"
    for row in doc["fn_tables"]:
        assert set(row) == FIELDS, row


def test_fn_tables_round_trip_through_json(py_index):
    again = ScaIndex.from_dict(json.loads(json.dumps(py_index.to_dict())))
    assert again.fn_tables == py_index.fn_tables


def test_unknown_table_kind_is_a_schema_error(py_index):
    doc = py_index.to_dict()
    doc["fn_tables"][0]["kind"] = "bogus"
    with pytest.raises(SchemaError):
        ScaIndex.from_dict(doc)


def test_index_marks_that_it_looked_for_tables(py_index):
    from spindlebox.extract import INDEX_MARKERS

    assert "fn_tables" in INDEX_MARKERS
    assert "fn_tables" in py_index.markers


# ------------------------------------------------------- python ast detection

def test_python_module_dict_of_functions(py_index):
    t = _table(py_index, f"{OPS}.HANDLERS")
    assert t.kind == "dict"
    assert t.key_type == "str"
    assert t.file == "pkg/ops.py"
    assert t.members == [f"{OPS}.alpha_handler", f"{OPS}.on_beta"]
    start = _line_of("pkg/ops.py", "HANDLERS = {")
    assert t.span == (start, start + 3)


def test_python_module_list_of_functions(py_index):
    t = _table(py_index, f"{OPS}.PIPE")
    assert t.kind == "list"
    assert t.key_type == "int"
    assert t.members == [f"{OPS}.first_step", f"{OPS}.second_step"]


def test_python_decorator_registry_with_nested_entries(py_index):
    t = _table(py_index, f"{OPS}.OPS")
    assert t.kind == "registry"
    assert t.members == [f"{OPS}.upper_op", f"{OPS}.lower_op"]


def test_python_register_call_registry(py_index):
    t = _table(py_index, f"{OPS}.HOOKS")
    assert t.kind == "registry"
    assert t.members == [f"{OPS}.hook_one"]


def test_packaging_entry_points(py_index):
    scripts = _table(py_index, "pyproject.project.scripts")
    assert scripts.kind == "entry_points"
    assert scripts.key_type == "str"
    assert scripts.file == "pyproject.toml"
    assert scripts.members == ["pkg.cli.run_tool"]
    plugins = _table(py_index, "pyproject.project.entry-points.demo.plugins")
    assert plugins.members == ["pkg.cli.activate"]


def test_a_dict_of_non_functions_is_not_a_table(tmp_path):
    (tmp_path / "m.py").write_text('NAMES = {"a": "x", "b": 2}\n\ndef f():\n    return NAMES\n')
    idx = build_index(tmp_path, langs=["python"])
    assert idx.fn_tables == []
    assert "fn_tables" not in idx.to_dict()


# ------------------------------------------------- profile-declared detection

def test_every_profile_declares_fn_tables_explicitly():
    for path in sorted(PROFILE_DIR.glob("*.json")):
        spec = json.loads(path.read_text()).get("fn_tables")
        assert isinstance(spec, dict), f"{path.name}: no 'fn_tables' key"
        why = spec.get("absent") or spec.get("unsupported")
        if why is not None:
            assert isinstance(why, str) and why.strip(), path.name
        else:
            assert spec.get("declarations") and spec.get("containers"), path.name
    assert profile_registry.fn_tables_for("python") is not None


@pytest.mark.parametrize("lang", ["javascript", "typescript", "go", "rust", "c"])
def test_profile_languages_detect_dict_and_list_tables(lang):
    idx = build_index(FIXTURE / lang, project_name=f"fntables_{lang}", langs=[lang])
    by_name = {t.address.rsplit(".", 1)[-1]: t for t in idx.fn_tables}
    assert set(by_name) == {"HANDLERS", "PIPE"}, [t.address for t in idx.fn_tables]
    names = {i.address: i.name for i in idx.items}
    handlers, pipe = by_name["HANDLERS"], by_name["PIPE"]
    assert handlers.kind == "dict" and handlers.key_type == "str"
    assert [names[m] for m in handlers.members] in (
        ["alpha_handler", "on_beta"], ["alphaHandler", "onBeta"])
    assert pipe.kind == "list" and pipe.key_type == "int"
    assert [names[m] for m in pipe.members] in (
        ["first_step", "second_step"], ["firstStep", "secondStep"])
    assert all(t.file and t.span[0] <= t.span[1] for t in idx.fn_tables)


# ---------------------------------------------------------------- validate

def test_validate_flags_a_heterogeneous_table(py_index):
    errors, warnings = validate_index(py_index)
    assert not errors, errors
    assert any(f"{OPS}.MIXED" in w and "homogeneous" in w for w in warnings), warnings
    assert not any(f"{OPS}.HANDLERS" in m for m in errors + warnings)
    strict_errors, _ = validate_index(py_index, strict=True)
    assert any(f"{OPS}.MIXED" in e for e in strict_errors)


def test_validate_rejects_a_table_member_missing_from_the_index(py_index):
    idx = ScaIndex.from_dict(py_index.to_dict())
    _table(idx, f"{OPS}.HANDLERS").members.append(f"{OPS}.nowhere")
    errors, _ = validate_index(idx)
    assert any(f"{OPS}.HANDLERS" in e and f"{OPS}.nowhere" in e for e in errors), errors


# -------------------------------------------------------------------- gaps

def _dead(idx: ScaIndex) -> set[str]:
    return {g["address"] for g in find_gaps(idx) if g["kind"] == "dead_item"}


def test_gaps_counts_membership_in_a_reachable_table_as_liveness(py_index):
    dead = _dead(py_index)
    for name in ("alpha_handler", "on_beta", "first_step", "second_step", "upper_op",
                 "lower_op", "hook_one", "unary", "binary"):
        assert f"{OPS}.{name}" not in dead, name


def test_gaps_counts_entry_point_members_as_live(py_index):
    dead = _dead(py_index)
    assert "pkg.cli.run_tool" not in dead
    assert "pkg.cli.activate" not in dead


def test_gaps_still_reports_a_member_of_an_unreachable_table(py_index):
    assert f"{OPS}.orphan" in _dead(py_index)


# --------------------------------------------------------------- callgraph

def test_callgraph_fans_out_to_every_member_at_one_over_n(py_index):
    from spindlebox.fn_tables import fan_out_edges

    edges = {(e["caller"], e["callee"]): e for e in fan_out_edges(py_index)}
    e = edges[(f"{OPS}.dispatch", f"{OPS}.alpha_handler")]
    assert e["strength"] == pytest.approx(0.5)
    assert e["table"] == f"{OPS}.HANDLERS"
    assert edges[(f"{OPS}.dispatch", f"{OPS}.on_beta")]["strength"] == pytest.approx(0.5)
    assert edges[(f"{OPS}.run_op", f"{OPS}.upper_op")]["strength"] == pytest.approx(0.5)
    assert edges[(f"{OPS}.fire", f"{OPS}.hook_one")]["strength"] == pytest.approx(1.0)
    assert not any(c == f"{OPS}.orphan" for _, c in edges)


def test_workflows_mine_through_a_table_edge(py_index):
    flows = mine_workflows(py_index, min_confidence=0.3)
    pairs = {(a, b) for f in flows for a, b in zip(f["addresses"], f["addresses"][1:], strict=False)}
    assert (f"{OPS}.dispatch", f"{OPS}.alpha_handler") in pairs


# ------------------------------------------------------------- self-evidence

def test_spindlebox_report_ops_are_not_dead_in_its_own_index():
    idx = build_index(REPO, project_name="spindlebox", langs=["python"])
    t = _table(idx, "spindlebox.reporting.REPORT_OPS")
    assert t.kind == "registry"
    assert "spindlebox.reporting.render_findings" in t.members
    assert "spindlebox.reporting.render_findings" not in _dead(idx)
