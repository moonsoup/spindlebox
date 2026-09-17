"""Out-of-package plugins: discovered, namespaced, and never able to break the core.

A plugin extends SPIndlebox; it does not get to change it. Every test here is
about that asymmetry -- an absent, broken, or badly-behaved plugin must leave
the fifteen built-in commands exactly as they were, because those are what the
global rule and other projects' scripts call.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from spindlebox import plugins, reporting

REPO = Path(__file__).parent.parent


class FakeEntryPoint:
    """What importlib.metadata hands back, without needing an install."""

    def __init__(self, name, value, loader=None):
        self.name = name
        self.value = value
        self._loader = loader

    def load(self):
        if self._loader is None:
            raise ImportError(f"cannot import {self.value}")
        return self._loader()


class FakePlugin:
    def __init__(self, name="fake", api=None, stack_dir=None, ops=(), cli=None):
        self.name = name
        self.api = plugins.PLUGIN_API if api is None else api
        self.stack_dir = stack_dir
        self._ops = ops
        self._cli = cli

    def register_ops(self, register):
        for op, requires, provides in self._ops:
            register(op, lambda ctx: ctx, requires=requires, provides=provides)

    def cli(self, argv):
        return self._cli(argv) if self._cli else 0


@pytest.fixture
def no_plugins(monkeypatch):
    monkeypatch.setattr(plugins, "_entry_points", lambda: [])
    plugins.forget()
    yield
    plugins.forget()


@pytest.fixture
def one_plugin(monkeypatch):
    def install(plugin):
        monkeypatch.setattr(
            plugins, "_entry_points",
            lambda: [FakeEntryPoint(plugin.name, "fake.mod", lambda: plugin)])
        plugins.forget()
        return plugin
    yield install
    plugins.forget()


# --- an absent plugin changes nothing ---------------------------------------

def test_without_plugins_the_stacks_are_the_builtin_ones(no_plugins) -> None:
    assert reporting.all_stacks() == reporting.list_stacks()


def test_discovery_is_skippable_by_environment(monkeypatch, one_plugin) -> None:
    one_plugin(FakePlugin())
    monkeypatch.setenv("SPINDLEBOX_PLUGINS", "none")
    plugins.forget()
    assert plugins.loaded() == {}
    assert reporting.all_stacks() == reporting.list_stacks()


def test_a_named_selection_loads_only_those(monkeypatch, one_plugin) -> None:
    one_plugin(FakePlugin(name="fake"))
    monkeypatch.setenv("SPINDLEBOX_PLUGINS", "other")
    plugins.forget()
    assert plugins.loaded() == {}


def test_metadata_is_read_without_importing_the_plugin(monkeypatch) -> None:
    """A built-in command must not pay for -- or be broken by -- a plugin's
    import. `show --span` is on the hot path for the global read-narrowly rule
    and for another project's gate script."""
    def explode():
        raise AssertionError("the plugin was imported during name lookup")

    monkeypatch.setattr(plugins, "_entry_points",
                        lambda: [FakeEntryPoint("fake", "fake.mod", explode)])
    plugins.forget()
    assert plugins.names() == ["fake"]


# --- a broken plugin is reported, never fatal -------------------------------

def test_a_plugin_that_will_not_import_is_a_problem_not_a_crash(monkeypatch) -> None:
    monkeypatch.setattr(plugins, "_entry_points",
                        lambda: [FakeEntryPoint("fake", "fake.mod", None)])
    plugins.forget()
    assert plugins.loaded() == {}
    assert [name for name, _ in plugins.problems()] == ["fake"]
    assert "cannot import" in plugins.problems()[0][1]


def test_an_api_mismatch_is_refused_with_both_numbers(one_plugin) -> None:
    one_plugin(FakePlugin(api=plugins.PLUGIN_API + 1))
    assert plugins.loaded() == {}
    why = plugins.problems()[0][1]
    assert str(plugins.PLUGIN_API) in why and str(plugins.PLUGIN_API + 1) in why


def test_a_plugin_may_not_take_a_builtin_command_name(one_plugin) -> None:
    one_plugin(FakePlugin(name="index"))
    assert plugins.loaded() == {}
    assert "built-in" in plugins.problems()[0][1]


def test_a_plugin_whose_name_disagrees_with_its_entry_point_is_refused(
        monkeypatch) -> None:
    monkeypatch.setattr(
        plugins, "_entry_points",
        lambda: [FakeEntryPoint("declared", "fake.mod",
                                lambda: FakePlugin(name="actual"))])
    plugins.forget()
    assert plugins.loaded() == {}


# --- ops are namespaced and may not displace anything -----------------------

def test_a_plugin_op_is_registered_under_its_own_prefix(one_plugin) -> None:
    one_plugin(FakePlugin(ops=[("fake.analyse", set(), {"rows"})]))
    plugins.loaded()
    assert "fake.analyse" in reporting.REPORT_OPS


def test_an_unprefixed_op_is_refused(one_plugin) -> None:
    one_plugin(FakePlugin(ops=[("analyse", set(), {"rows"})]))
    assert plugins.loaded() == {}
    assert "fake." in plugins.problems()[0][1]
    assert "analyse" not in reporting.REPORT_OPS


def test_a_plugin_cannot_overwrite_a_builtin_op(one_plugin) -> None:
    before = reporting.REPORT_OPS["render.table"]["fn"]
    one_plugin(FakePlugin(name="render", ops=[("render.table", set(), {"output"})]))
    plugins.loaded()
    assert reporting.REPORT_OPS["render.table"]["fn"] is before


# --- stacks -----------------------------------------------------------------

def test_a_plugin_stack_is_listed_under_its_namespace(one_plugin, tmp_path) -> None:
    (tmp_path / "thing.stack.json").write_text(json.dumps({
        "report": "thing", "description": "a plugin report",
        "stages": ["fake.analyse", "render.table"], "ctx": {}, "default_format": "md"}))
    one_plugin(FakePlugin(stack_dir=tmp_path,
                          ops=[("fake.analyse", set(), {"title", "columns", "rows"})]))
    stacks = reporting.all_stacks()
    assert "fake:thing" in stacks
    assert set(reporting.list_stacks()) <= set(stacks)


def test_a_plugin_stack_cannot_shadow_a_builtin_report(one_plugin, tmp_path) -> None:
    (tmp_path / "typing-health.stack.json").write_text(json.dumps({
        "report": "typing-health", "description": "hijack",
        "stages": ["render.table"], "ctx": {}, "default_format": "md"}))
    one_plugin(FakePlugin(stack_dir=tmp_path))
    stacks = reporting.all_stacks()
    assert stacks["typing-health"] == reporting.list_stacks()["typing-health"]
    assert "fake:typing-health" in stacks


# --- the CLI ----------------------------------------------------------------

def _cli(*args, env=None):
    return subprocess.run([sys.executable, "-m", "spindlebox", *args],
                          capture_output=True, text=True, cwd=REPO, env=env)


def test_the_plugins_command_lists_what_is_installed() -> None:
    done = _cli("plugins")
    assert done.returncode == 0, done.stderr


def test_an_unknown_command_still_fails_like_argparse() -> None:
    done = _cli("nonsuch")
    assert done.returncode == 2, done.stdout + done.stderr


def test_the_reserved_names_are_the_real_commands() -> None:
    """Two lists of the built-in commands would drift, and the drift would
    show up as a plugin quietly shadowing a command."""
    from spindlebox import cli

    actions = cli.build_parser()._subparsers._group_actions[0].choices
    assert set(actions) == set(plugins.BUILTIN_COMMANDS)
