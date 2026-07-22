"""Context normalization: give every item a canonical ctx-in → ctx-out convention.

Each function's real parameters map onto keys of one shared context; its return
value lands back in the context under a stable key. This is what makes
heterogeneous functions uniform (→ Vec<Box<dyn FnMut(&mut Ctx)>> in Rust).

Key rule: ctx key = param name. Same key with the same normalized type is
shared between items; a type conflict renames the later item's key
(name-prefixed, then group-prefixed, then numbered) so ctx_schema stays
type-consistent.
"""

from __future__ import annotations

import re

from findexer.schema import Item

_IDENT_BAD = re.compile(r"[^A-Za-z0-9_]")


def _sanitize(key: str) -> str:
    key = _IDENT_BAD.sub("_", key)
    if not key or key[0].isdigit():
        key = "_" + key
    return key


def _place(schema: dict[str, str], key: str, norm_type: str, prefixes: list[str]) -> str:
    """Find a key (renaming via prefixes/counters on type conflict) and record it."""
    candidates = [key] + [f"{p}_{key}" for p in prefixes]
    n = 2
    for cand in candidates:
        cand = _sanitize(cand)
        if schema.get(cand, norm_type) == norm_type:
            schema[cand] = norm_type
            return cand
    base = _sanitize(candidates[-1])
    while schema.get(f"{base}{n}", norm_type) != norm_type:
        n += 1
    schema[f"{base}{n}"] = norm_type
    return f"{base}{n}"


def apply_ctx_normalization(items: list[Item]) -> dict[str, str]:
    """Build ctx adapters for every item (in place); return the ctx_schema union."""
    schema: dict[str, str] = {}
    for item in sorted(items, key=lambda i: i.ordinal):
        group_pfx = _sanitize(item.group.replace(".", "_"))
        requires: dict[str, str] = {}
        param_map: dict[str, str] = {}
        for p in item.signature.params:
            if p.kind in ("receiver", "kwvariadic"):
                continue
            key = _place(schema, p.name, p.norm_type, [item.name, group_pfx])
            if p.default is None:
                requires[key] = p.norm_type  # defaulted params are optional inputs
            param_map[p.name] = f"ctx.{key}"
        provides: dict[str, str] = {}
        return_key: str | None = None
        if item.signature.returns_norm != "unit":
            return_key = _place(
                schema, f"{item.name}_result", item.signature.returns_norm, [group_pfx]
            )
            provides[return_key] = item.signature.returns_norm
        item.ctx_adapter.requires = requires
        item.ctx_adapter.provides = provides
        item.ctx_adapter.param_map = param_map
        item.ctx_adapter.return_key = return_key
        item.deps.ctx_keys_required = list(requires)
    return schema
