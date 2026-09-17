"""Which projects a run is about -- asked once, for every consumer.

Three answers were in three places: this registry, another tool's directory
listing, and a third tool reading projectMan's database. The op below is the
one answer. It differs from `_iter_indexes` in one way that matters: a project
it cannot use is REPORTED, not dropped.
"""

from __future__ import annotations

import pytest

from spindlebox import registry
from spindlebox.facts import projects as facts_projects


def _run(ctx):
    return facts_projects.select_projects(dict(ctx))


def test_one_root_is_one_project(tmp_path) -> None:
    (tmp_path / "alpha").mkdir()
    out = _run({"root": str(tmp_path / "alpha")})
    assert [p["name"] for p in out["projects"]] == ["alpha"]


def test_every_directory_under_a_root_is_a_project(tmp_path) -> None:
    for name in ("alpha", "beta"):
        (tmp_path / name).mkdir()
    (tmp_path / ".cache").mkdir()
    (tmp_path / "notes.txt").write_text("not a project\n")
    out = _run({"under": str(tmp_path)})
    assert [p["name"] for p in out["projects"]] == ["alpha", "beta"]


def test_the_registry_answers_when_nothing_else_is_asked(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("SPINDLEBOX_HOME", str(home))
    (tmp_path / "alpha").mkdir()
    registry.register("alpha", str(tmp_path / "alpha"),
                      str(tmp_path / "alpha" / ".spi" / "index.json"))
    assert [p["name"] for p in _run({})["projects"]] == ["alpha"]


def test_a_root_that_is_gone_is_reported_not_dropped(tmp_path, monkeypatch) -> None:
    """`_iter_indexes` skips a missing index in silence, so a project can
    vanish from a sweep without a word. A negative finding has to say where it
    looked."""
    home = tmp_path / "home"
    monkeypatch.setenv("SPINDLEBOX_HOME", str(home))
    registry.register("ghost", str(tmp_path / "ghost"),
                      str(tmp_path / "ghost" / ".spi" / "index.json"))
    out = _run({})
    assert out["projects"] == []
    assert out["skipped"] and "ghost" in out["skipped"][0]["why"]


def test_a_project_without_an_index_is_still_a_project(tmp_path, monkeypatch) -> None:
    """Ziggurat's checks read source, not the SPI, so an unindexed project is
    perfectly analysable -- which is why this cannot filter on the index."""
    home = tmp_path / "home"
    monkeypatch.setenv("SPINDLEBOX_HOME", str(home))
    (tmp_path / "alpha").mkdir()
    registry.register("alpha", str(tmp_path / "alpha"),
                      str(tmp_path / "alpha" / ".spi" / "index.json"))
    out = _run({})
    assert [p["name"] for p in out["projects"]] == ["alpha"]
    assert out["projects"][0]["index"] is None


def test_root_beats_under_beats_the_registry(tmp_path) -> None:
    (tmp_path / "alpha").mkdir()
    (tmp_path / "beta").mkdir()
    out = _run({"root": str(tmp_path / "alpha"), "under": str(tmp_path)})
    assert [p["name"] for p in out["projects"]] == ["alpha"]


def test_a_missing_root_argument_is_an_error_not_an_empty_answer(tmp_path) -> None:
    with pytest.raises(facts_projects.NoSuchProject):
        _run({"root": str(tmp_path / "nonsuch")})


def test_the_op_is_registered_for_stacks() -> None:
    from spindlebox import reporting
    assert "select.projects" in reporting.REPORT_OPS
    assert "projects" in reporting.REPORT_OPS["select.projects"]["provides"]
