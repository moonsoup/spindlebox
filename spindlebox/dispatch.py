"""Live invocation of indexed Python items through the normalized context."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from spindlebox.schema import Item, ScaIndex


class DispatchError(Exception):
    pass


def resolve_item(index: ScaIndex, selector: str) -> Item:
    item = None
    if selector.isdigit():
        item = index.item_by_ordinal(int(selector))
    if item is None:
        item = index.item_by_address(selector)
    if item is None:
        raise DispatchError(f"no item matches '{selector}'")
    return item


def call_item(index: ScaIndex, root: str | Path, selector: str, ctx: dict[str, Any]) -> dict:
    """Invoke a Python item by ordinal/address, feeding params from the ctx dict.

    Returns the ctx merged with the item's return value under its return_key.
    """
    item = resolve_item(index, selector)
    if item.language != "python":
        raise DispatchError(f"'{item.address}' is {item.language}; only Python items are callable")
    if item.kind != "function":
        raise DispatchError(
            f"'{item.address}' is a {item.kind}; only module-level functions are callable"
        )
    path = Path(root) / item.file
    module_name = "spindlebox_target_" + item.file.replace("/", "_").removesuffix(".py")
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise DispatchError(f"cannot load module at {path}")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(Path(root)))
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        raise DispatchError(f"import of {item.file} failed: {e}") from e
    finally:
        sys.path.remove(str(Path(root)))
    try:
        fn = getattr(module, item.name)
    except AttributeError as e:
        raise DispatchError(f"module {item.file} has no attribute '{item.name}'") from e

    kwargs: dict[str, Any] = {}
    for p in item.signature.params:
        if p.kind in ("receiver", "variadic", "kwvariadic"):
            continue
        ctx_ref = item.ctx_adapter.param_map.get(p.name)
        key = ctx_ref.removeprefix("ctx.") if ctx_ref else p.name
        if key in ctx:
            kwargs[p.name] = ctx[key]
        elif p.default is None:
            raise DispatchError(f"missing required ctx key '{key}' for param '{p.name}'")
    result = fn(**kwargs)
    out = dict(ctx)
    if item.ctx_adapter.return_key:
        out[item.ctx_adapter.return_key] = result
    return out


def run_pipeline(index: ScaIndex, root: str | Path, name: str,
                 ctx: dict[str, Any]) -> dict:
    """Execute a defined pipeline stage by stage, applying its edge bindings.

    Edges carry stage N's result into stage N+1's input key — without them a
    direct chain is type-approved but never composes (double→triple would
    yield triple(x), not triple(double(x))).
    """
    pipe = next((p for p in index.pipelines if p.name == name), None)
    if pipe is None:
        raise DispatchError(f"no pipeline named '{name}' "
                            f"(have: {[p.name for p in index.pipelines]})")
    stages = []
    for ordinal in pipe.stages:
        item = index.item_by_ordinal(ordinal)
        if item is None:
            raise DispatchError(f"pipeline '{name}' references unknown ordinal {ordinal}")
        stages.append(item)
    from spindlebox.validate import pipeline_edges
    edges = pipe.edges or pipeline_edges(stages)
    by_after: dict[int, list[dict]] = {}
    for e in edges:
        by_after.setdefault(e["after"], []).append(e)

    out = dict(ctx)
    prev_ordinal: int | None = None
    for item in stages:
        if prev_ordinal is not None:
            for e in by_after.get(prev_ordinal, ()):
                if e["from_key"] in out:
                    out[e["to_key"]] = out[e["from_key"]]
        out = call_item(index, root, item.address, out)
        prev_ordinal = item.ordinal
    return out
