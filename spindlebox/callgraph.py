"""Composition analysis past one hop: SCCs, depth and a fixed point (#41).

Every other analysis asks a one-hop question ("does this have a caller?").
Behaviour that exists only through composition -- a chain six calls deep, two
functions that recurse through each other, a cluster of dead code that keeps
itself "alive" by calling itself -- needs the whole graph. This module builds
that graph from the index alone (it is pure: no file is read, nothing runs)
and answers three questions about it:

- **chains**: every composed chain from an item, enumerated to ``depth``
  stages (default 4). A chain is a walk, not a simple path, so a cycle shows
  up as a repeated address instead of silently ending the chain. A chain that
  stops at ``depth`` while its last stage still has successors says so
  (``continues``); nothing is dropped.
- **classification**: when a chain from an item goes past ``depth``, the item
  is classified by a fixed point over the strongly connected components:
  ``unbounded: "n"`` with the cycle it enters, or ``finite: k``, the longest
  path in stages over the condensation DAG. Tarjan emits components
  successors-first, so one pass in that order reaches the least fixed point of
  ``depth(c) = 1 + max(depth(succ))`` -- every component is settled before
  anything that reaches it is.
- **reachability**: which items no entry point can reach (``gaps`` reports the
  ones that are live only through each other as an ``unreachable_island``).

An edge A->B is one of four kinds, strongest first:

- ``call``      A calls B by its resolved address;
- ``indirect``  A makes an ``ambiguous:`` call naming B (B is one of several
                same-named items -- credited to each, as ``gaps`` does);
- ``table``     A calls through a ``fn_table`` holding B (``fn_tables``);
- ``ctx``       A provides a ctx key B requires (producer -> consumer).

A ``param:`` call goes to whatever the caller passed in; the index does not
record the argument, so it has no target and adds no edge.
"""

from __future__ import annotations

from spindlebox.fn_tables import fan_out_strengths
from spindlebox.schema import ScaIndex

DEFAULT_DEPTH = 4
EDGE_KINDS = ("call", "indirect", "table", "ctx")
UNBOUNDED = "n"

#: successor address -> edge kind, per source address
Graph = dict[str, dict[str, str]]


def build_graph(idx: ScaIndex) -> Graph:
    """Every item's outgoing edges, one kind per edge (the strongest that applies)."""
    rank = {k: i for i, k in enumerate(EDGE_KINDS)}
    graph: Graph = {it.address: {} for it in idx.items}

    def add(a: str, b: str, kind: str) -> None:
        if b not in graph:
            return
        old = graph[a].get(b)
        if old is None or rank[kind] < rank[old]:
            graph[a][b] = kind

    by_name: dict[str, list[str]] = {}
    for it in idx.items:
        by_name.setdefault(it.name, []).append(it.address)
    for it in idx.items:
        for call in it.deps.calls:
            if call.startswith("ambiguous:"):
                name = call[len("ambiguous:"):].rsplit(".", 1)[-1]
                for b in by_name.get(name, []):
                    if b != it.address:
                        add(it.address, b, "indirect")
            elif call in graph:
                add(it.address, call, "call")
    for (a, b), _strength in fan_out_strengths(idx.items, idx.fn_tables).items():
        if a in graph:
            add(a, b, "table")
    consumers: dict[str, list[str]] = {}
    for it in idx.items:
        for key in it.ctx_adapter.requires:
            consumers.setdefault(key, []).append(it.address)
    for it in idx.items:
        for key in it.ctx_adapter.provides:
            for b in consumers.get(key, []):
                if b != it.address:
                    add(it.address, b, "ctx")
    return graph


def strongly_connected(graph: Graph) -> list[list[str]]:
    """Tarjan's SCCs, iteratively, emitted successors-first (reverse topological)."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    out: list[list[str]] = []
    counter = 0
    for start in sorted(graph):
        if start in index:
            continue
        work = [(start, iter(sorted(graph[start])))]
        index[start] = low[start] = counter
        counter += 1
        stack.append(start)
        on_stack.add(start)
        while work:
            node, succs = work[-1]
            advanced = False
            for nxt in succs:
                if nxt not in index:
                    index[nxt] = low[nxt] = counter
                    counter += 1
                    stack.append(nxt)
                    on_stack.add(nxt)
                    work.append((nxt, iter(sorted(graph[nxt]))))
                    advanced = True
                    break
                if nxt in on_stack:
                    low[node] = min(low[node], index[nxt])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                comp = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    comp.append(w)
                    if w == node:
                        break
                out.append(sorted(comp))
    return out


def is_cyclic(comp: list[str], graph: Graph) -> bool:
    """More than one member, or one member that calls itself (direct recursion)."""
    return len(comp) > 1 or comp[0] in graph[comp[0]]


def classify(graph: Graph) -> dict[str, dict]:
    """Address -> ``{"finite": k}`` or ``{"unbounded": "n", "cycle": [...]}``.

    ``k`` counts stages (items) on the longest path from the address; a cyclic
    component on the way makes it unbounded, and ``cycle`` names the members of
    one it enters: its own component when that is cyclic, else the first (by
    address) of those its successors enter.
    """
    comps = strongly_connected(graph)
    comp_of = {a: i for i, comp in enumerate(comps) for a in comp}
    settled: list[dict] = []
    for i, comp in enumerate(comps):
        if is_cyclic(comp, graph):
            settled.append({"unbounded": UNBOUNDED, "cycle": comp})
            continue
        succ = sorted({comp_of[b] for a in comp for b in graph[a]} - {i})
        unbounded = [settled[j] for j in succ if "unbounded" in settled[j]]
        if unbounded:
            first = min(unbounded, key=lambda r: r["cycle"])
            settled.append({"unbounded": UNBOUNDED, "cycle": first["cycle"]})
        else:
            settled.append({"finite": 1 + max((settled[j]["finite"] for j in succ), default=0)})
    return {a: settled[comp_of[a]] for a in graph}


def chains(graph: Graph, start: str, depth: int = DEFAULT_DEPTH) -> list[dict]:
    """Every maximal walk from ``start`` of at most ``depth`` stages.

    ``continues`` is True when the walk stopped only because it reached
    ``depth``; ``via`` is the kind of each edge taken.
    """
    out: list[dict] = []
    work: list[tuple[list[str], list[str]]] = [([start], [])]
    while work:
        path, via = work.pop()
        succs = sorted(graph[path[-1]])
        if succs and len(path) < depth:
            for nxt in reversed(succs):
                work.append((path + [nxt], via + [graph[path[-1]][nxt]]))
            continue
        out.append({"addresses": path, "via": via, "depth": len(path),
                    "continues": bool(succs)})
    return out


def reachable(graph: Graph, roots: set[str]) -> set[str]:
    seen = set(roots) & set(graph)
    todo = list(seen)
    while todo:
        for b in graph[todo.pop()]:
            if b not in seen:
                seen.add(b)
                todo.append(b)
    return seen


def emergent(idx: ScaIndex, depth: int = DEFAULT_DEPTH) -> dict:
    """The whole report: cyclic components, and per item its chains and classification.

    Every item is a root -- one with no outgoing edge is ``finite: 1`` with a
    single one-stage chain -- so a consumer filters; this never caps.
    """
    if depth < 1:
        raise ValueError("depth must be at least 1")
    graph = build_graph(idx)
    ordinal = {it.address: it.ordinal for it in idx.items}
    fixed: dict[str, dict] | None = None
    roots = []
    for address in sorted(graph, key=lambda a: ordinal[a]):
        walks = chains(graph, address, depth)
        past = any(c["continues"] for c in walks)
        if past:
            # the chain goes past `depth`: settle it by the fixed point
            fixed = fixed if fixed is not None else classify(graph)
            verdict = dict(fixed[address])
        else:
            verdict = {"finite": max(c["depth"] for c in walks)}
        roots.append({"address": address, "ordinal": ordinal[address],
                      **verdict, "past_depth": past, "chains": walks})
    cycles = [{"members": comp, "ordinals": [ordinal[a] for a in comp]}
              for comp in strongly_connected(graph) if is_cyclic(comp, graph)]
    return {
        "depth": depth,
        "items": len(graph),
        "edges": sum(len(v) for v in graph.values()),
        "cycles": sorted(cycles, key=lambda c: c["members"]),
        "roots": roots,
    }
