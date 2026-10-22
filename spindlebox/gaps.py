"""`spindlebox gaps` — find gaps in the software from the SPI alone.

Five gap kinds, all computed from index data already present:
- dead_item:          no in-index caller, not an entrypoint, no ctx provider/consumer edge,
                      not a member of a reached ``fn_table`` (a dispatch table, registry
                      or entry-point group something calls through -- #40)
- unprovided_ctx_key: a ctx key some item requires that no item provides
- unresolvable_call:  a bare called name that is neither an item nor an import (likely typo)
                      (a language's builtins arrive already marked ``builtin:`` by
                      extraction, so this module knows no language's builtins -- #37;
                      its standard-library names arrive on ``deps.stdlib_calls`` -- #38)

Entry points arrive the same way: extraction stamps ``item.entry_point`` from the
language profile. Which markers an index carries is listed in ``idx.markers``;
for an index built before a marker existed, this module falls back to the
heuristic it used before (#38).
- near_duplicate:     items of one signature class with the same ctx shape and a shared name stem
- unreachable_island: items no entry point reaches that are not all dead_items -- a group
                      that calls itself (mutual or direct recursion, or a dead item's private
                      helpers) and so reads as live to the one-hop dead_item check (#41)
"""

from __future__ import annotations

import re

from spindlebox import callgraph
from spindlebox.depmap import import_root
from spindlebox.extract.profile_registry import known_call_names
from spindlebox.fn_tables import live_members
from spindlebox.schema import Item, ScaIndex

_ENTRYPOINT_NAMES = {"main", "__init__", "__main__", "setup"}
_CAMEL = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")


def _is_entrypoint(item: Item) -> bool:
    """The pre-#38 heuristic, kept for indexes whose ``markers`` lack ``entry_points``."""
    name = item.name
    if name in _ENTRYPOINT_NAMES or name.startswith(("cmd_", "test_", "handle_")):
        return True
    if "test" in item.file.lower() or item.kind == "script_main":
        return True
    return False


def _entry_point_check(idx: ScaIndex):
    if "entry_points" in idx.markers:
        return lambda item: item.entry_point is not None
    return _is_entrypoint


def _name_tokens(name: str) -> set[str]:
    return {t.lower() for t in _CAMEL.findall(name) if len(t) > 1}


def _reverse_call_map(items: list[Item]) -> dict[str, set[str]]:
    """Callee address -> set of caller addresses.

    An ``ambiguous:`` call names something this index defines more than once, so
    the edge is real but its target is unknown. Every same-named item is
    credited as possibly-called: over-crediting risks missing a genuinely dead
    item, while under-crediting reports live code as dead — and the second error
    is the one that made `gaps` unusable (#17).
    """
    by_name: dict[str, list[str]] = {}
    for item in items:
        by_name.setdefault(item.name, []).append(item.address)

    callers: dict[str, set[str]] = {}
    for item in items:
        for callee in item.deps.calls:
            if callee.startswith("ambiguous:"):
                name = callee[len("ambiguous:"):].rsplit(".", 1)[-1]
                for address in by_name.get(name, []):
                    if address != item.address:
                        callers.setdefault(address, set()).add(item.address)
            elif not callee.startswith(("external:", "builtin:")):
                callers.setdefault(callee, set()).add(item.address)
    return callers


def _dead_items(idx: ScaIndex) -> list[dict]:
    callers = _reverse_call_map(idx.items)
    all_provides: set[str] = set()
    all_requires: set[str] = set()
    for it in idx.items:
        all_provides |= set(it.ctx_adapter.provides)
        all_requires |= set(it.ctx_adapter.requires)
    is_entry = _entry_point_check(idx)
    in_reached_table = live_members(idx)
    out = []
    for item in idx.items:
        if item.address in callers or is_entry(item) or item.address in in_reached_table:
            continue
        provides_edge = bool(set(item.ctx_adapter.provides) & all_requires)
        consumes_edge = bool(set(item.ctx_adapter.requires) & all_provides)
        if provides_edge or consumes_edge:
            continue
        out.append({
            "kind": "dead_item", "address": item.address, "ordinal": item.ordinal,
            "severity": "medium",
            "detail": f"{item.name}: no in-index caller and no context edge",
        })
    return out


def _unreachable_islands(idx: ScaIndex, dead: set[str]) -> list[dict]:
    """Groups of items reachable from no root, where some member has a caller.

    The roots are what ``dead_item`` already treats as live without a caller:
    entry points, members of a reached table, and items with a ctx edge. Every
    edge kind of ``callgraph`` is followed from them. The unreachable rest is
    split into weakly connected groups; a group made only of dead_items is
    already reported, so only a group with a member that *has* a caller -- and
    so reads as live -- is an island.
    """
    graph = callgraph.build_graph(idx)
    is_entry = _entry_point_check(idx)
    in_reached_table = live_members(idx)
    has_ctx_edge = {a for a, outs in graph.items() if "ctx" in outs.values()}
    has_ctx_edge |= {b for outs in graph.values() for b, kind in outs.items() if kind == "ctx"}
    roots = {it.address for it in idx.items
             if is_entry(it) or it.address in in_reached_table} | has_ctx_edge
    lost = set(graph) - callgraph.reachable(graph, roots)
    neighbours: dict[str, set[str]] = {a: set() for a in lost}
    for a in lost:
        for b in graph[a]:
            if b in lost:
                neighbours[a].add(b)
                neighbours[b].add(a)
    ordinal = {it.address: it.ordinal for it in idx.items}
    out = []
    seen: set[str] = set()
    for start in sorted(lost):
        if start in seen:
            continue
        group, todo = {start}, [start]
        while todo:
            for b in neighbours[todo.pop()] - group:
                group.add(b)
                todo.append(b)
        seen |= group
        if group <= dead:
            continue
        members = sorted(group)
        out.append({
            "kind": "unreachable_island", "members": members,
            "ordinals": sorted(ordinal[a] for a in members), "severity": "medium",
            "detail": f"{len(members)} item(s) only reached from each other or from "
                      f"dead code, never from an entry point",
        })
    return out


def _unprovided_ctx_keys(idx: ScaIndex) -> list[dict]:
    provided = set(idx.ctx_schema) & {
        k for it in idx.items for k in it.ctx_adapter.provides
    }
    provided |= {k for it in idx.items for k in it.ctx_adapter.provides}
    out = []
    seen: set[str] = set()
    for item in idx.items:
        for key in item.ctx_adapter.requires:
            if key in provided or key in seen:
                continue
            seen.add(key)
            high = key.endswith("_result")  # producer naming convention → expected a producer
            out.append({
                "kind": "unprovided_ctx_key", "address": item.address,
                "ordinal": item.ordinal, "detail": key,
                "severity": "high" if high else "low",
            })
    return out


def _unresolvable_calls(idx: ScaIndex) -> list[dict]:
    import_roots: set[str] = set()
    for item in idx.items:
        for imp in item.deps.imports:
            import_roots.add(import_root(imp))
        import_roots |= set(item.deps.external_packages)
    # an index built before extraction marked runtime names: re-derive them from
    # the item's profile rather than report every builtin as a typo (#38)
    legacy = not {"builtin_calls", "stdlib_calls"} <= set(idx.markers)
    out = []
    seen: set[tuple[str, str]] = set()
    for item in idx.items:
        for call in item.deps.calls:
            if not call.startswith("external:"):
                continue
            raw = call[len("external:"):]
            if "." in raw:  # attribute/method call — not a bare missing symbol
                continue
            if raw in import_roots or raw in item.deps.stdlib_calls:
                continue
            if legacy and raw in known_call_names(item.language):
                continue
            key = (item.address, raw)
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "kind": "unresolvable_call", "address": item.address,
                "ordinal": item.ordinal, "detail": raw, "severity": "medium",
            })
    return out


def _near_duplicates(idx: ScaIndex) -> list[dict]:
    # group by (signature class, exact required-key set): identical interface + inputs
    groups: dict[tuple, list[Item]] = {}
    for item in idx.items:
        key = (item.sig_class, frozenset(item.ctx_adapter.requires))
        groups.setdefault(key, []).append(item)
    out = []
    for (sig_class, _req), members in groups.items():
        if len(members) < 2:
            continue
        # cluster members that pairwise share a name token (distinguishes a real
        # duplicate family from two unrelated fns that merely share a signature)
        clusters: list[list[Item]] = []
        for item in members:
            toks = _name_tokens(item.name)
            placed = False
            for cluster in clusters:
                if any(toks & _name_tokens(m.name) for m in cluster):
                    cluster.append(item)
                    placed = True
                    break
            if not placed:
                clusters.append([item])
        for cluster in clusters:
            if len(cluster) < 2:
                continue
            out.append({
                "kind": "near_duplicate", "sig_class": sig_class,
                "members": sorted(m.address for m in cluster),
                "ordinals": sorted(m.ordinal for m in cluster),
                "severity": "low",
                "detail": f"{len(cluster)} items share signature {sig_class} and "
                          f"ctx inputs — consolidation candidate",
            })
    return out


def find_gaps(idx: ScaIndex) -> list[dict]:
    dead = _dead_items(idx)
    gaps = (dead + _unprovided_ctx_keys(idx)
            + _unresolvable_calls(idx) + _near_duplicates(idx)
            + _unreachable_islands(idx, {g["address"] for g in dead}))
    order = {"high": 0, "medium": 1, "low": 2}
    gaps.sort(key=lambda g: (order.get(g["severity"], 3), g["kind"], g.get("address", "")))
    return gaps
