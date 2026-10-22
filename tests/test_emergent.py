"""Composition analysis past one hop (#41).

``fixtures/miniproj_emergent`` spells one program in every profiled language:
``main`` calls ``step1`` (the head of a six-deep chain ``step1 -> ... -> step6``)
and ``ping`` (mutually recursive with ``pong``); ``lonely_a`` and ``lonely_b``
call each other and nothing reaches them. Each has a caller, so before #41 none
of them read as dead, and nothing measured how deep a chain goes.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from spindlebox.extract import build_index
from spindlebox.gaps import find_gaps
from spindlebox.workflows import mine_workflows

REPO = Path(__file__).parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "miniproj_emergent"


class _Lazy:
    """``spindlebox.callgraph`` imported on use, so each test fails on its own."""

    def __getattr__(self, name):
        import importlib
        return getattr(importlib.import_module("spindlebox.callgraph"), name)


callgraph = _Lazy()


def _languages() -> list[str]:
    from spindlebox.extract import base
    from spindlebox.extract.profile_registry import all_profiles
    base._register_profiles()
    return sorted(set(base.ALL_LANGS) | set(all_profiles()))


@pytest.fixture(scope="module")
def indexes():
    return {lang: build_index(FIXTURE / lang, project_name=f"emergent_{lang}", langs=[lang])
            for lang in _languages()}


def _addr(idx, name):
    return next(it.address for it in idx.items if it.name == name)


def _names(idx, addresses):
    name_of = {it.address: it.name for it in idx.items}
    return {name_of[a] for a in addresses}


def _root(report, address):
    return next(r for r in report["roots"] if r["address"] == address)


def test_fixture_covers_every_language():
    missing = [lang for lang in _languages()
               if not any(p.is_file() for p in (FIXTURE / lang).glob("*"))]
    assert not missing, f"no emergent program for: {missing}"


# ----------------------------------------------------------- callgraph module

def test_callgraph_is_pure_and_reads_only_the_index():
    tree = ast.parse((REPO / "spindlebox" / "callgraph.py").read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    allowed = {"__future__", "spindlebox.schema", "spindlebox.fn_tables"}
    assert imported <= allowed, imported - allowed
    calls = {n.func.id for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not calls & {"open", "print", "exec", "eval", "input", "__import__"}


def test_six_deep_chain_is_finite_6(indexes):
    for lang, idx in indexes.items():
        report = callgraph.emergent(idx)
        root = _root(report, _addr(idx, "step1"))
        assert root["finite"] == 6, (lang, root)
        assert "unbounded" not in root, lang
        assert root["past_depth"] is True, lang
        assert _root(report, _addr(idx, "step3"))["finite"] == 4, lang
        assert _root(report, _addr(idx, "step6"))["finite"] == 1, lang


def test_chains_enumerated_to_depth_4(indexes):
    for lang, idx in indexes.items():
        root = _root(callgraph.emergent(idx), _addr(idx, "step1"))
        chains = [[_names(idx, [a]).pop() for a in c["addresses"]] for c in root["chains"]]
        assert ["step1", "step2", "step3", "step4"] in chains, (lang, chains)
        assert all(len(c) <= 4 for c in chains), lang
        deepest = next(c for c in root["chains"] if c["depth"] == 4)
        assert deepest["continues"] is True, lang
        assert deepest["via"] == ["call", "call", "call"], lang


def test_mutual_recursion_is_unbounded(indexes):
    for lang, idx in indexes.items():
        report = callgraph.emergent(idx)
        for name in ("ping", "pong", "main"):
            root = _root(report, _addr(idx, name))
            assert root["unbounded"] == "n", (lang, name, root)
            assert "finite" not in root, (lang, name)
            assert _names(idx, root["cycle"]) == {"ping", "pong"}, (lang, name, root)
        cycles = [_names(idx, c["members"]) for c in report["cycles"]]
        assert {"ping", "pong"} in cycles and {"lonely_a", "lonely_b"} in cycles, (lang, cycles)


def test_unreachable_island_gap(indexes):
    for lang, idx in indexes.items():
        gaps = find_gaps(idx)
        islands = [_names(idx, g["members"]) for g in gaps if g["kind"] == "unreachable_island"]
        assert islands == [{"lonely_a", "lonely_b"}], (lang, islands)
        dead = {g["address"] for g in gaps if g["kind"] == "dead_item"}
        assert not dead & {_addr(idx, "lonely_a"), _addr(idx, "lonely_b")}, lang
        json.dumps(gaps)


def test_workflows_report_cycle_and_truncated(indexes):
    for lang, idx in indexes.items():
        flows = {tuple(_names(idx, [a]).pop() for a in f["addresses"]): f
                 for f in mine_workflows(idx)}
        for f in flows.values():
            assert "truncated" in f and "cycle" in f, (lang, f)
        rec = flows[("main", "ping", "pong")]
        assert _names(idx, rec["cycle"]) == {"ping", "pong"}, (lang, rec)
        assert rec["truncated"] is False
        chain = flows[("main", "step1", "step2", "step3", "step4", "step5", "step6")]
        assert chain["cycle"] is None and chain["truncated"] is False, lang


# ------------------------------------------------- synthetic Python, all edge kinds

@pytest.fixture(scope="module")
def py_edges(tmp_path_factory):
    root = tmp_path_factory.mktemp("edges")
    (root / "mod.py").write_text(
        "def load():\n    return 1\n\n\n"
        "def consume(load_result):\n    return load_result\n\n\n"
        "def op_a():\n    return 1\n\n\n"
        "def op_b():\n    return 2\n\n\n"
        "OPS = {'a': op_a, 'b': op_b}\n\n\n"
        "def dispatch(name):\n    return OPS[name]()\n\n\n"
        "def recurse(n):\n    return recurse(n - 1)\n\n\n"
        "def selfish(n):\n    return selfish(n - 1)\n\n\n"
        "def main():\n    dispatch('a')\n    recurse(3)\n"
    )
    for i in range(10):
        nxt = f"return d{i + 1}()" if i < 9 else "return 0"
        (root / f"deep{i}.py").write_text(
            (f"from deep{i + 1} import d{i + 1}\n\n\n" if i < 9 else "")
            + f"def d{i}():\n    {nxt}\n")
    return build_index(root, project_name="edges", langs=["python"])


def test_edge_kinds_table_and_ctx(py_edges):
    g = callgraph.build_graph(py_edges)
    assert g["mod.dispatch"]["mod.op_a"] == "table"
    assert g["mod.load"]["mod.consume"] == "ctx"
    assert g["mod.main"]["mod.dispatch"] == "call"


def test_direct_recursion_is_visible(py_edges):
    report = callgraph.emergent(py_edges)
    root = _root(report, "mod.recurse")
    assert root["unbounded"] == "n" and root["cycle"] == ["mod.recurse"]
    assert ["mod.recurse"] in [c["members"] for c in report["cycles"]]
    islands = [g["members"] for g in find_gaps(py_edges) if g["kind"] == "unreachable_island"]
    assert ["mod.selfish"] in islands


def test_workflows_truncated_is_flagged(py_edges):
    flows = mine_workflows(py_edges)
    deep = [f for f in flows if f["addresses"][0] == "deep0.d0"]
    assert deep and all(f["truncated"] is True for f in deep), deep


def test_depth_parameter_and_no_silent_cap(py_edges):
    report = callgraph.emergent(py_edges, depth=2)
    assert report["depth"] == 2
    root = _root(report, "deep0.d0")
    assert root["finite"] == 10 and root["past_depth"] is True
    assert all(c["depth"] <= 2 for c in root["chains"])
    assert len(report["roots"]) == len(py_edges.items)


# --------------------------------------------------------------------- the CLI

def test_emergent_command(tmp_path):
    env = {"PATH": "/usr/bin:/bin", "SPINDLEBOX_HOME": str(tmp_path / "home"),
           "HOME": str(tmp_path / "home"), "SPINDLEBOX_PLUGINS": "none"}
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "prog.py").write_text((FIXTURE / "python" / "prog.py").read_text())
    run = [sys.executable, "-m", "spindlebox"]
    r = subprocess.run(run + ["index", str(proj), "--name", "proj"], capture_output=True,
                       text=True, env=env, cwd=REPO)
    assert r.returncode == 0, r.stderr
    r = subprocess.run(run + ["emergent", "--project", "proj", "--json"], capture_output=True,
                       text=True, env=env, cwd=REPO)
    assert r.returncode == 0, r.stderr
    doc = json.loads(r.stdout)
    assert _root(doc, "prog.step1")["finite"] == 6
    r = subprocess.run(run + ["emergent", "--project", "proj"], capture_output=True,
                       text=True, env=env, cwd=REPO)
    assert r.returncode == 0, r.stderr
    assert "finite: 6" in r.stdout and "unbounded: n" in r.stdout
    r = subprocess.run(run + ["gaps", "--project", "proj", "--kind", "unreachable_island"],
                       capture_output=True, text=True, env=env, cwd=REPO)
    assert r.returncode == 0, r.stderr
    assert "prog.lonely_a, prog.lonely_b" in r.stdout


def test_emergent_is_documented():
    text = (REPO / "docs" / "guide" / "analysis.md").read_text()
    assert "## spindlebox emergent" in text
    assert "unreachable_island" in text
    assert "`truncated`" in text and "`cycle`" in text
    src = (REPO / "tests" / "test_docs_examples.py").read_text()
    assert '"emergent"' in src
