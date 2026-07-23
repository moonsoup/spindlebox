import json
from pathlib import Path

import pytest

from spindlebox import reporting
from spindlebox.cli import main as cli_main
from spindlebox.extract import build_index

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def two_projects(tmp_path, monkeypatch):
    """Two fixture projects indexed into an isolated registry."""
    monkeypatch.setenv("SPINDLEBOX_HOME", str(tmp_path / "home"))
    from spindlebox import registry
    for name in ("miniproj_py", "miniproj_go"):
        root = tmp_path / name
        root.mkdir()
        for f in (FIXTURES / name).iterdir():
            if f.is_file():
                (root / f.name).write_text(f.read_text())
        idx = build_index(root, project_name=name)
        out = root / ".spi" / "index.json"
        out.parent.mkdir()
        out.write_text(json.dumps(idx.to_dict()))
        registry.register(name, str(root), str(out))
    return tmp_path


def test_stacks_load_and_validate():
    stacks = reporting.list_stacks()
    assert {"typing-health", "dup-candidates", "compile-matrix", "score-history"} <= set(stacks)
    for name, stack in stacks.items():
        assert reporting.check_stack(stack) == [], name


def test_check_catches_bad_stack():
    errs = reporting.check_stack({"report": "x", "stages": ["nope.missing"], "ctx": {}})
    assert any("unknown op" in e for e in errs)
    errs = reporting.check_stack(
        {"report": "x", "stages": ["collect.typing_health"], "ctx": {}})
    assert any("output" in e for e in errs)


def test_check_catches_unsatisfied_requires():
    errs = reporting.check_stack(
        {"report": "x", "stages": ["collect.score_history", "render.table"], "ctx": {}})
    assert any("state_dir" in e for e in errs)


def test_typing_health_all_formats(two_projects):
    stack = reporting.list_stacks()["typing-health"]
    for fmt, probe in (("md", "| project |"), ("csv", "project,items"),
                       ("html", "<table>"), ("json", '"rows"')):
        ctx = reporting.run_stack(stack, {"format": fmt})
        assert probe in ctx["output"]
        assert "miniproj_py" in ctx["output"]


def test_typing_health_project_filter(two_projects):
    stack = reporting.list_stacks()["typing-health"]
    ctx = reporting.run_stack(stack, {"project": "miniproj_go"})
    assert "miniproj_go" in ctx["output"]
    assert "miniproj_py" not in ctx["output"]


def test_dup_candidates_finds_cross_language_twin(two_projects):
    # miniproj_py and miniproj_go both define read_lines / ReadLines with the
    # same signature class — the exact duplication the report exists to expose
    stack = reporting.list_stacks()["dup-candidates"]
    ctx = reporting.run_stack(stack, {"format": "json"})
    rows = json.loads(ctx["output"])["rows"]
    assert any("miniproj_go" in r["projects"] and "miniproj_py" in r["projects"]
               for r in rows)


def test_compile_matrix_covers_all_backends(two_projects):
    stack = reporting.list_stacks()["compile-matrix"]
    ctx = reporting.run_stack(stack, {"format": "json"})
    rows = json.loads(ctx["output"])["rows"]
    assert rows and all(r["rust"].startswith("ok") and r["java"].startswith("ok")
                        for r in rows)


def test_cli_list_and_run(two_projects, capsys):
    assert cli_main(["report", "--list"]) == 0
    assert "typing-health" in capsys.readouterr().out
    assert cli_main(["report", "typing-health", "--format", "csv"]) == 0
    assert "untyped_pct" in capsys.readouterr().out


def test_cli_out_file(two_projects, tmp_path, capsys):
    out = tmp_path / "r.html"
    assert cli_main(["report", "dup-candidates", "--format", "html",
                     "--out", str(out)]) == 0
    assert out.read_text().startswith("<!doctype html>")


def test_compile_matrix_surfaces_backend_failure(two_projects, monkeypatch):
    """The FAIL branch must actually fire — a report that can only say 'ok'
    verifies nothing (no healthy project had ever exercised it)."""
    from spindlebox import generate as gen_pkg

    class ExplodingBackend:
        name = "boom"

        def generate(self, idx, options):
            raise RuntimeError("deliberate")

    monkeypatch.setitem(gen_pkg.BACKENDS, "boom", ExplodingBackend)
    stack = reporting.list_stacks()["compile-matrix"]
    ctx = reporting.run_stack(stack, {"format": "json"})
    rows = json.loads(ctx["output"])["rows"]
    assert rows and all(r["boom"] == "FAIL: RuntimeError" for r in rows)
    assert all(r["rust"].startswith("ok") for r in rows)  # healthy backends unaffected
