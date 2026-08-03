"""`spindlebox workflows` — mine candidate pipelines across functions from the SPI.

A directed edge A->B is proposed when A calls B, or when A provides a ctx key
B requires. Each edge gets a confidence weight; candidate workflows are the
maximal simple paths whose every edge clears a threshold. Output is
`pipeline define`-compatible (ordered addresses + ordinals), so an accepted
candidate feeds straight into the existing pipeline machinery.
"""

from __future__ import annotations

from spindlebox.schema import Item, ScaIndex

# edge confidence = W_CALL*calls + W_CTX*ctx_coverage + W_GROUP*same_group_subtree
W_CALL = 0.5
W_CTX = 0.4
W_GROUP = 0.1
MAX_PATH = 8       # cap path length (real call graphs can be deep)
MAX_FLOWS = 200    # cap emitted candidates


def _same_subtree(a: Item, b: Item) -> bool:
    """Kept as the original boolean predicate; `_group_affinity` supersedes it for
    scoring but this stays for any caller relying on the plain question."""
    ga, gb = a.group, b.group
    return ga == gb or ga.startswith(gb + ".") or gb.startswith(ga + ".")


def _group_affinity(a: Item, b: Item) -> float:
    """Graded proximity in the group tree, 1.0 (same group) down to 0.0 (unrelated).

    The boolean version made every same-group call edge score exactly
    W_CALL + W_GROUP = 0.6 — precisely the default threshold — so admitted edges
    had no spread at all (#17).
    """
    ga, gb = a.group.split("."), b.group.split(".")
    shared = 0
    for x, y in zip(ga, gb, strict=False):
        if x != y:
            break
        shared += 1
    depth = max(len(ga), len(gb))
    return shared / depth if depth else 0.0


def _call_strength(a: Item, b: Item, name_counts: dict[str, int]) -> float:
    """1.0 for a resolved call; a fraction for an ambiguous one.

    An `ambiguous:` edge (see depmap.resolve_calls) names something this index
    defines more than once, so it is real evidence that *one* of the candidates is
    called. Splitting the weight across candidates keeps the edge visible without
    asserting a target the index cannot identify.
    """
    if b.address in a.deps.calls:
        return 1.0
    for call in a.deps.calls:
        if call.startswith("ambiguous:") and call[len("ambiguous:"):].rsplit(".", 1)[-1] == b.name:
            return 1.0 / max(name_counts.get(b.name, 1), 1)
    return 0.0


def _edge_confidence(a: Item, b: Item, name_counts: dict[str, int] | None = None) -> float:
    if a.address == b.address:
        return 0.0
    calls = _call_strength(a, b, name_counts or {})
    req = set(b.ctx_adapter.requires)
    ctx_cov = len(set(a.ctx_adapter.provides) & req) / len(req) if req else 0.0
    if calls == 0.0 and ctx_cov == 0.0:
        return 0.0
    return round(W_CALL * calls + W_CTX * ctx_cov + W_GROUP * _group_affinity(a, b), 4)


def _build_edges(items: list[Item], min_confidence: float) -> dict[str, list[tuple[str, float]]]:
    name_counts: dict[str, int] = {}
    for item in items:
        name_counts[item.name] = name_counts.get(item.name, 0) + 1
    edges: dict[str, list[tuple[str, float]]] = {}
    for a in items:
        for b in items:
            conf = _edge_confidence(a, b, name_counts)
            if conf >= min_confidence and conf > 0:
                edges.setdefault(a.address, []).append((b.address, conf))
    return edges


#: Default edge threshold. 0.6 was exactly W_CALL + W_GROUP — the score of the
#: commonest edge (a call within one group) — so it admitted only top-of-range
#: edges, all identical. Measured on this repo: 0.6 yields 1 distinct strength
#: across 200 candidates; 0.5 yields 38, for the same candidate count (#17).
DEFAULT_MIN_CONFIDENCE = 0.5


def mine_workflows(idx: ScaIndex, min_confidence: float = DEFAULT_MIN_CONFIDENCE) -> list[dict]:
    items = idx.items
    by_addr = {i.address: i for i in items}
    edges = _build_edges(items, min_confidence)
    has_incoming = {b for outs in edges.values() for b, _ in outs}
    sources = [a for a in edges if a not in has_incoming] or list(edges)

    flows: list[dict] = []

    def walk(path: list[str], confs: list[float], visiting: set[str]) -> None:
        if len(flows) >= MAX_FLOWS:
            return
        last = path[-1]
        extended = False
        if len(path) < MAX_PATH:
            for nxt, conf in sorted(edges.get(last, []), key=lambda e: -e[1]):
                if nxt in visiting:
                    continue
                extended = True
                walk(path + [nxt], confs + [conf], visiting | {nxt})
        if not extended and len(path) >= 2:
            flows.append({
                "addresses": list(path),
                "ordinals": [by_addr[a].ordinal for a in path],
                # `confidence` is the weakest link and gates admission — unchanged.
                # But min() against a threshold drives every candidate toward the
                # threshold value, which is why they were indistinguishable (#17).
                # `strength` is the mean edge weight, so candidates can be ranked.
                "confidence": round(min(confs), 4),
                "strength": round(sum(confs) / len(confs), 4),
                "stages": len(path),
            })

    for src in sorted(sources):
        walk([src], [], {src})

    # dedup identical paths, keep highest confidence, rank
    unique: dict[tuple, dict] = {}
    for f in flows:
        k = tuple(f["addresses"])
        if k not in unique or f["confidence"] > unique[k]["confidence"]:
            unique[k] = f
    # Rank by strength first: confidence alone cannot order candidates that all sit
    # at the admission threshold.
    ranked = sorted(unique.values(),
                    key=lambda f: (-f["strength"], -f["confidence"], -f["stages"]))
    return ranked[:MAX_FLOWS]
