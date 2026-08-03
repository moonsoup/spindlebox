"""Registry hygiene: dangling entries must be findable and removable.

Regression cover for #16 — the registry accumulated entries for moved, deleted
and temporary projects, so `search --all-projects` (the headline anti-bloat
feature) covered one real project plus a test fixture out of ~40 repos.
"""

import json

import pytest

from spindlebox import registry


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SPINDLEBOX_HOME", str(tmp_path / "home"))
    return tmp_path


def make_index_file(root, name):
    d = root / name / ".spi"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "index.json"
    p.write_text(json.dumps({"items": []}), encoding="utf-8")
    return p


class TestDangling:
    def test_empty_registry_has_none(self, home):
        assert registry.dangling() == []

    def test_live_entry_is_not_dangling(self, home):
        idx = make_index_file(home, "alive")
        registry.register("alive", str(home / "alive"), str(idx))
        assert registry.dangling() == []

    def test_missing_index_file_is_dangling(self, home):
        registry.register("ghost", str(home / "ghost"), str(home / "ghost/.spi/index.json"))
        assert registry.dangling() == ["ghost"]

    def test_reports_sorted_names(self, home):
        for n in ("zeta", "alpha"):
            registry.register(n, str(home / n), str(home / n / ".spi/index.json"))
        assert registry.dangling() == ["alpha", "zeta"]

    def test_mixed_registry_reports_only_the_dead(self, home):
        idx = make_index_file(home, "alive")
        registry.register("alive", str(home / "alive"), str(idx))
        registry.register("dead", str(home / "dead"), str(home / "dead/.spi/index.json"))
        assert registry.dangling() == ["dead"]


class TestPrune:
    def test_removes_dangling_entries(self, home):
        idx = make_index_file(home, "alive")
        registry.register("alive", str(home / "alive"), str(idx))
        registry.register("dead", str(home / "dead"), str(home / "dead/.spi/index.json"))
        removed = registry.prune()
        assert removed == ["dead"]
        assert list(registry.list_projects()) == ["alive"]

    def test_dry_run_reports_without_removing(self, home):
        registry.register("dead", str(home / "dead"), str(home / "dead/.spi/index.json"))
        removed = registry.prune(dry_run=True)
        assert removed == ["dead"]
        assert "dead" in registry.list_projects()

    def test_prune_on_clean_registry_is_a_no_op(self, home):
        idx = make_index_file(home, "alive")
        registry.register("alive", str(home / "alive"), str(idx))
        assert registry.prune() == []
        assert list(registry.list_projects()) == ["alive"]

    def test_never_touches_live_entries(self, home):
        for n in ("a", "b"):
            registry.register(n, str(home / n), str(make_index_file(home, n)))
        registry.register("dead", str(home / "dead"), str(home / "dead/.spi/index.json"))
        registry.prune()
        assert sorted(registry.list_projects()) == ["a", "b"]


class TestExcludeTests:
    """`search` should not surface test functions as reusable code by default-able flag."""

    def test_identifies_test_addresses(self):
        assert registry.is_test_address("tests.test_cli.test_index_creates") is True
        assert registry.is_test_address("packages.core.test.plans_test#183") is True
        assert registry.is_test_address("spindlebox.cli.cmd_index") is False

    def test_does_not_flag_words_merely_containing_test(self):
        assert registry.is_test_address("app.latest.refresh") is False
        assert registry.is_test_address("app.contested.value") is False

    def test_flags_spec_files_too(self):
        assert registry.is_test_address("web.src.button_spec.renders") is True


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
