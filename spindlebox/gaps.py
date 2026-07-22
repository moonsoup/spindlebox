"""`spindlebox gaps` — find gaps in the software from the SPI alone.

Four gap kinds, all computed from index data already present:
- dead_item:          no in-index caller, not an entrypoint, no ctx provider/consumer edge
- unprovided_ctx_key: a ctx key some item requires that no item provides
- unresolvable_call:  a bare called name that is neither an item nor an import (likely typo)
- near_duplicate:     items of one signature class with the same ctx shape and a shared name stem
"""

from __future__ import annotations

import builtins
import re

from spindlebox.schema import Item, ScaIndex

_BUILTINS = set(dir(builtins))
_ENTRYPOINT_NAMES = {"main", "__init__", "__main__", "setup"}
_CAMEL = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")


def _is_entrypoint(item: Item) -> bool:
    name = item.name
    if name in _ENTRYPOINT_NAMES or name.startswith(("cmd_", "test_", "handle_")):
        return True
    if "test" in item.file.lower() or item.kind == "script_main":
        return True
    return False


def _name_tokens(name: str) -> set[str]:
    return {t.lower() for t in _CAMEL.findall(name) if len(t) > 1}


def _reverse_call_map(items: list[Item]) -> dict[str, set[str]]:
    callers: dict[str, set[str]] = {}
    for item in items:
        for callee in item.deps.calls:
            if not callee.startswith("external:"):
                callers.setdefault(callee, set()).add(item.address)
    return callers


def _dead_items(idx: ScaIndex) -> list[dict]:
    callers = _reverse_call_map(idx.items)
    all_provides: set[str] = set()
    all_requires: set[str] = set()
    for it in idx.items:
        all_provides |= set(it.ctx_adapter.provides)
        all_requires |= set(it.ctx_adapter.requires)
    out = []
    for item in idx.items:
        if item.address in callers or _is_entrypoint(item):
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
            import_roots.add(imp.split(".")[0].split("/")[0])
        import_roots |= set(item.deps.external_packages)
    out = []
    seen: set[tuple[str, str]] = set()
    for item in idx.items:
        for call in item.deps.calls:
            if not call.startswith("external:"):
                continue
            raw = call[len("external:"):]
            if "." in raw:  # attribute/method call — not a bare missing symbol
                continue
            if raw in _BUILTINS or raw in import_roots:
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
    gaps = (_dead_items(idx) + _unprovided_ctx_keys(idx)
            + _unresolvable_calls(idx) + _near_duplicates(idx))
    order = {"high": 0, "medium": 1, "low": 2}
    gaps.sort(key=lambda g: (order.get(g["severity"], 3), g["kind"], g.get("address", "")))
    return gaps
