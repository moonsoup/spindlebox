"""Analysis over ``fn_tables``: which tables are reached, and the edges they add (#40).

A call through a table is recorded at extraction as ``table:<address>`` (#39).
This module pairs those calls with the tables extraction found, so analysis
can treat a dispatch like ``OPS[name]["fn"](ctx)`` as what it is: a call to one
of the table's members, not knowable which. It reads only the index.

- A table is *reached* when some item calls through it, or when it is a
  package's ``entry_points`` (the outside world calls those).
- ``gaps`` counts membership in a reached table as liveness.
- The call graph gets a fan-out edge from each caller to every member of the
  table it calls through, at strength ``1/n`` for ``n`` members -- the same
  split as an ``ambiguous:`` call, for the same reason.
"""

from __future__ import annotations

from spindlebox.schema import FnTable, Item, ScaIndex

TABLE_PREFIX = "table:"


def table_for_call(call: str, tables: list[FnTable]) -> FnTable | None:
    """The table a ``table:<address>`` call goes through, or None.

    An exact address wins. Otherwise -- a table imported from another module is
    addressed at extraction by the caller's module -- the one table whose last
    address segment matches, if exactly one does.
    """
    if not call.startswith(TABLE_PREFIX):
        return None
    address = call[len(TABLE_PREFIX):]
    for t in tables:
        if t.address == address:
            return t
    leaf = address.rsplit(".", 1)[-1]
    hits = [t for t in tables if t.address.rsplit(".", 1)[-1] == leaf]
    return hits[0] if len(hits) == 1 else None


def table_callers(items: list[Item], tables: list[FnTable]) -> dict[str, list[str]]:
    """Table address -> addresses of the items that call through it."""
    out: dict[str, list[str]] = {}
    for item in items:
        for call in item.deps.calls:
            t = table_for_call(call, tables)
            if t is not None and item.address not in out.setdefault(t.address, []):
                out[t.address].append(item.address)
    return out


def reached_tables(idx: ScaIndex) -> list[FnTable]:
    """Tables something calls through, and every ``entry_points`` table."""
    callers = table_callers(idx.items, idx.fn_tables)
    return [t for t in idx.fn_tables if t.kind == "entry_points" or t.address in callers]


def live_members(idx: ScaIndex) -> dict[str, str]:
    """Member address -> address of a reached table holding it."""
    out: dict[str, str] = {}
    for t in reached_tables(idx):
        for m in t.members:
            out.setdefault(m, t.address)
    return out


def fan_out_strengths(items: list[Item], tables: list[FnTable]) -> dict[tuple[str, str], tuple[float, str]]:
    """(caller, member) -> (1/n, table address) for every call through a table.

    A caller dispatching through two tables that share a member keeps the
    stronger edge.
    """
    out: dict[tuple[str, str], tuple[float, str]] = {}
    for item in items:
        for call in item.deps.calls:
            t = table_for_call(call, tables)
            if t is None or not t.members:
                continue
            strength = 1.0 / len(t.members)
            for m in t.members:
                key = (item.address, m)
                if key not in out or out[key][0] < strength:
                    out[key] = (strength, t.address)
    return out


def fan_out_edges(idx: ScaIndex) -> list[dict]:
    """The call graph's table edges: ``{caller, callee, table, strength}``."""
    return [
        {"caller": caller, "callee": callee, "table": table, "strength": strength}
        for (caller, callee), (strength, table)
        in sorted(fan_out_strengths(idx.items, idx.fn_tables).items())
    ]
