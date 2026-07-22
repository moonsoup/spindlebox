"""Addressing: hierarchical dotted addresses, sticky ordinals, range selectors."""

from __future__ import annotations

import posixpath
import re
from typing import Any

_RANGE_RE = re.compile(r"^\d+(-\d+)?(,\s*\d+(-\d+)?)*$")


def parse_ranges(s: str) -> list[int]:
    """'12-14,55' → [12, 13, 14, 55]."""
    out: list[int] = []
    for part in s.split(","):
        part = part.strip()
        if "-" in part:
            a_s, b_s = part.split("-", 1)
            a, b = int(a_s), int(b_s)
            if b < a:
                raise ValueError(f"descending range: {part}")
            out.extend(range(a, b + 1))
        else:
            out.append(int(part))
    return out


def parse_selector(s: str) -> list[int] | str:
    """Ordinal range selector → list of ordinals; anything else → address/group path."""
    s = s.strip()
    if _RANGE_RE.match(s):
        return parse_ranges(s)
    return s


_ANON_NAMES = {"", "<lambda>", "<anonymous>", "<closure>"}


def module_parts(rel_file: str) -> list[str]:
    """Path → address components: ext stripped, __init__ dropped, dots sanitized."""
    stem = posixpath.splitext(rel_file.replace("\\", "/"))[0]
    parts = [p for p in stem.split("/") if p not in ("", ".", "__init__")]
    return [p.replace(".", "_") for p in parts]


def make_address(rel_file: str, scope_chain: list[str], name: str, line: int) -> str:
    """Dotted hierarchical address: path (ext stripped, / → .) + scope chain + name.

    Anonymous items (lambdas, unnamed closures) address as <scope>#<line>.
    """
    parts = module_parts(rel_file)
    parts += list(scope_chain)
    if name in _ANON_NAMES or name.startswith("<"):
        return ".".join(parts) + f"#{line}"
    return ".".join([*parts, name])


def _get(item: Any, key: str) -> Any:
    return item[key] if isinstance(item, dict) else getattr(item, key)


def _set(item: Any, key: str, value: Any) -> None:
    if isinstance(item, dict):
        item[key] = value
    else:
        setattr(item, key, value)


def assign_ordinals(
    items: list[Any], old_map: dict[str, int], old_retired: list[int]
) -> list[int]:
    """Assign sticky ordinals in place; return the updated retired list.

    Items must already be in deterministic order (sorted by file, start line).
    Addresses present in old_map keep their ordinal; new addresses take the next
    integer above every ordinal ever used (live or retired) — ordinals are never
    reused, so range queries stay stable across rebuilds.
    """
    used = set(old_map.values()) | set(old_retired)
    next_free = max(used, default=-1) + 1
    seen: set[str] = set()
    for item in items:
        addr = _get(item, "address")
        if addr in old_map:
            _set(item, "ordinal", old_map[addr])
            seen.add(addr)
        else:
            _set(item, "ordinal", next_free)
            next_free += 1
    retired = set(old_retired) | {o for a, o in old_map.items() if a not in seen}
    return sorted(retired)
