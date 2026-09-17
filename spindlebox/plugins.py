"""Out-of-package plugins: how something else extends SPIndlebox.

SPIndlebox is the platform; a plugin adds reports, ops and a subcommand to it.
The dependency runs ONE WAY -- a plugin imports spindlebox, and spindlebox never
imports a plugin by name. Discovery is by packaging metadata, so a plugin is
installed rather than registered by editing this tree.

The asymmetry is the whole contract, and every rule below serves it:

    a plugin's ops are namespaced `<plugin>.*` and may not displace an existing
    op, so a stack that worked yesterday cannot start meaning something else

    a plugin's stacks are named `<plugin>:<report>`, so they cannot shadow a
    built-in report

    a plugin may not take a built-in command's name, and the built-in commands
    are matched BEFORE discovery runs -- `spindlebox show --span` is on the hot
    path for the read-narrowly rule and for another project's gate script, and
    it must not pay for, or be broken by, somebody's plugin import

    a plugin that will not import, declares the wrong API, or misbehaves during
    registration is RECORDED as a problem and skipped. A checker whose plugin
    silently failed would report "nothing found" from having looked at nothing,
    which is the failure this estate keeps relearning.

`SPINDLEBOX_PLUGINS=none` disables discovery entirely; a comma-separated list
loads only those names. Tests and the documented examples set it, so an
operator's installed plugins cannot change what the docs promise.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

#: The contract version a plugin declares. Bumped only for a breaking change to
#: what spindlebox asks of a plugin; a plugin declaring anything else is skipped
#: rather than half-loaded.
PLUGIN_API = 1

#: The packaging entry-point group a plugin advertises itself in.
GROUP = "spindlebox.plugins"

#: Names a plugin may not take, because the CLI resolves these first. Pinned
#: against the real parser by a test, so the two cannot drift apart.
BUILTIN_COMMANDS = frozenset({
    "index", "show", "search", "deps", "stale", "validate", "call", "generate",
    "report", "pipeline", "projects", "gaps", "workflows", "install-skill",
    "plugins",
})

_ENV = "SPINDLEBOX_PLUGINS"

_loaded: dict[str, Plugin] | None = None
_problems: list[tuple[str, str]] = []
#: Ops this module added to the registry, so `forget()` can take them back
#: out. Without it a second load cycle in one process refuses its own ops as
#: already existing -- which is a real long-running-process bug, not just a
#: test artefact.
_registered: list[str] = []


@dataclass
class Plugin:
    """What spindlebox will use, taken from the object the entry point names."""

    name: str
    api: int
    stack_dir: Path | None
    register_ops: object | None
    cli: object | None
    value: str = ""


def _entry_points() -> list:
    """The raw entry points. Replaced wholesale in tests."""
    from importlib.metadata import entry_points

    try:
        return list(entry_points(group=GROUP))
    except Exception:  # noqa: BLE001 -- a broken environment is not our crash
        return []


def forget() -> None:
    """Drop the cache and un-register what was loaded, so asking again is clean."""
    global _loaded, _problems
    if _registered:
        from spindlebox import reporting

        for op in _registered:
            reporting.REPORT_OPS.pop(op, None)
        _registered.clear()
    _loaded, _problems = None, []


def _selection() -> set[str] | None:
    """None: load everything. A set: load only these. Empty set: load nothing."""
    raw = os.environ.get(_ENV)
    if raw is None:
        return None
    if raw.strip() == "none":
        return set()
    return {part.strip() for part in raw.split(",") if part.strip()}


def names() -> list[str]:
    """Plugin names from METADATA ONLY -- nothing is imported.

    This is what the CLI asks before deciding whether an unknown first word
    might be a plugin, so it must stay free of plugin code.
    """
    wanted = _selection()
    found = [ep.name for ep in _entry_points()]
    if wanted is None:
        return sorted(found)
    return sorted(name for name in found if name in wanted)


def problems() -> list[tuple[str, str]]:
    """(name, why) for every plugin that was found and not used."""
    if _loaded is None:
        loaded()
    return list(_problems)


def loaded() -> dict[str, Plugin]:
    """Every usable plugin, imported and registered. Cached."""
    global _loaded
    if _loaded is not None:
        return _loaded
    _loaded, _problems[:] = {}, []
    wanted = _selection()
    for ep in _entry_points():
        if wanted is not None and ep.name not in wanted:
            continue
        try:
            plugin = _accept(ep)
        except _Refused as refusal:
            _problems.append((ep.name, str(refusal)))
            continue
        except Exception as exc:  # noqa: BLE001 -- somebody else's import
            _problems.append((ep.name, f"{type(exc).__name__}: {exc}"))
            continue
        _loaded[plugin.name] = plugin
    return _loaded


class _Refused(Exception):
    """This plugin will not be used, and the report says why."""


def _accept(ep) -> Plugin:
    if ep.name in BUILTIN_COMMANDS:
        raise _Refused(f"{ep.name!r} is a built-in command name")
    obj = ep.load()
    declared = getattr(obj, "name", None)
    if declared != ep.name:
        raise _Refused(
            f"declares name {declared!r} but is installed as {ep.name!r}")
    api = getattr(obj, "api", None)
    if api != PLUGIN_API:
        raise _Refused(
            f"declares plugin API {api!r}; this spindlebox speaks {PLUGIN_API}")
    stack_dir = getattr(obj, "stack_dir", None)
    plugin = Plugin(name=ep.name, api=api,
                    stack_dir=Path(stack_dir) if stack_dir else None,
                    register_ops=getattr(obj, "register_ops", None),
                    cli=getattr(obj, "cli", None),
                    value=getattr(ep, "value", ""))
    if plugin.register_ops is not None:
        _register_ops(plugin)
    return plugin


def _register_ops(plugin: Plugin) -> None:
    """Take the plugin's ops, or none of them.

    Collected first and committed second, so a plugin that breaks half way
    through registration leaves nothing behind -- a partially registered
    plugin would fail a stack check in a way nobody could read.
    """
    from spindlebox import reporting  # late: reporting owns the registry

    staged: dict[str, dict] = {}

    def register(op: str, fn, requires=frozenset(), provides=frozenset()) -> None:
        if not op.startswith(f"{plugin.name}."):
            raise _Refused(f"op {op!r} must be named {plugin.name}.*")
        if op in reporting.REPORT_OPS:
            raise _Refused(f"op {op!r} already exists")
        staged[op] = {"fn": fn, "requires": set(requires), "provides": set(provides)}

    plugin.register_ops(register)
    reporting.REPORT_OPS.update(staged)
    _registered.extend(staged)


def stacks() -> dict[str, dict]:
    """Every plugin's stacks, keyed `<plugin>:<report>`."""
    out: dict[str, dict] = {}
    import json

    for plugin in loaded().values():
        if plugin.stack_dir is None or not plugin.stack_dir.is_dir():
            continue
        for path in sorted(plugin.stack_dir.glob("*.stack.json")):
            try:
                data = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError) as exc:
                _problems.append((plugin.name, f"{path.name}: {exc}"))
                continue
            report = data.get("report")
            if not report:
                _problems.append((plugin.name, f"{path.name}: no 'report' name"))
                continue
            out[f"{plugin.name}:{report}"] = data
    return out
