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
    ga, gb = a.group, b.group
    return ga == gb or ga.startswith(gb + ".") or gb.startswith(ga + ".")


def _edge_confidence(a: Item, b: Item) -> float:
    if a.address == b.address:
        return 0.0
    calls = 1.0 if b.address in a.deps.calls else 0.0
    req = set(b.ctx_adapter.requires)
    ctx_cov = len(set(a.ctx_adapter.provides) & req) / len(req) if req else 0.0
    if calls == 0.0 and ctx_cov == 0.0:
        return 0.0
    return round(W_CALL * calls + W_CTX * ctx_cov + W_GROUP * _same_subtree(a, b), 4)


def _build_edges(items: list[Item], min_confidence: float) -> dict[str, list[tuple[str, float]]]:
    edges: dict[str, list[tuple[str, float]]] = {}
    for a in items:
        for b in items:
            conf = _edge_confidence(a, b)
            if conf >= min_confidence and conf > 0:
                edges.setdefault(a.address, []).append((b.address, conf))
    return edges


def mine_workflows(idx: ScaIndex, min_confidence: float = 0.6) -> list[dict]:
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
                "confidence": round(min(confs), 4),
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
    ranked = sorted(unique.values(), key=lambda f: (-f["confidence"], -f["stages"]))
    return ranked[:MAX_FLOWS]
