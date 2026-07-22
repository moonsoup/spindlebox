"""Signature classes: the one-element-type-per-array rule.

A signature class id is built from normalized param/return types only —
names and source languages excluded — so equivalent functions in different
languages land in the same class.
"""

from __future__ import annotations

from spindlebox.schema import Group, Item, Signature


def sig_class_id(sig: Signature) -> str:
    parts = []
    for p in sig.params:
        if p.kind in ("receiver", "kwvariadic"):
            continue
        parts.append(("*" + p.norm_type) if p.kind == "variadic" else p.norm_type)
    return "sig:" + ",".join(parts) + "->" + sig.returns_norm


def build_signature_classes(items: list[Item]) -> dict[str, dict]:
    """sig_class id → {params, returns, members} across the whole index."""
    classes: dict[str, dict] = {}
    for item in items:
        sc = item.sig_class
        if sc not in classes:
            body = sc[len("sig:"):]
            params_s, _, returns = body.rpartition("->")
            # split on top-level commas only (generics contain commas too)
            params: list[str] = []
            depth = 0
            cur = ""
            for ch in params_s:
                if ch == "<":
                    depth += 1
                elif ch == ">":
                    depth -= 1
                if ch == "," and depth == 0:
                    params.append(cur)
                    cur = ""
                else:
                    cur += ch
            if cur:
                params.append(cur)
            classes[sc] = {"params": params, "returns": returns, "members": []}
        classes[sc]["members"].append(item.ordinal)
    return classes


def partition_op_arrays(group: Group, items_by_ordinal: dict[int, Item]) -> None:
    """Partition a group's members by sig_class into op_arrays (in place)."""
    arrays: dict[str, list[int]] = {}
    for ordinal in group.member_ordinals:
        item = items_by_ordinal[ordinal]
        arrays.setdefault(item.sig_class, []).append(ordinal)
    group.op_arrays = arrays
