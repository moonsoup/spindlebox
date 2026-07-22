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
