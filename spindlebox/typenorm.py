"""core-1 type vocabulary and per-language normalization.

Vocabulary: str, bytes, bool, i64, f64, unit, any, error, fn,
list<T>, map<K,V>, set<T>, option<T>, result<T,E>, tuple<...>, iter<T>, obj:<Name>.

sig_class ids are built from these, so two functions in different languages
with the same shape land in the same class.
"""

from __future__ import annotations


def _split_top(s: str, sep: str) -> list[str]:
    """Split on sep, ignoring separators nested inside any bracket pair."""
    parts: list[str] = []
    depth = 0
    cur = ""
    for ch in s:
        if ch in "[<({":
            depth += 1
        elif ch in "]>)}":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur.strip())
    return parts


def _generic(s: str, open_ch: str, close_ch: str) -> tuple[str, list[str]] | None:
    """Return (base, args) for 'Base<a, b>' style expressions, else None."""
    if not s.endswith(close_ch) or open_ch not in s:
        return None
    base, args_s = s.split(open_ch, 1)
    return base.strip(), _split_top(args_s[: -len(close_ch)], ",")


# ---------------------------------------------------------------- python

_PY_SIMPLE = {
    "str": "str", "int": "i64", "float": "f64", "bool": "bool", "bytes": "bytes",
    "bytearray": "bytes", "None": "unit", "NoneType": "unit", "Any": "any",
    "object": "any", "any": "any", "list": "list<any>", "dict": "map<any,any>",
    "set": "set<any>", "tuple": "tuple<>", "Callable": "fn", "callable": "fn",
}

_PY_LIST = {"list", "List", "Sequence", "MutableSequence"}
_PY_MAP = {"dict", "Dict", "Mapping", "MutableMapping", "OrderedDict", "defaultdict"}
_PY_SET = {"set", "Set", "frozenset", "FrozenSet", "MutableSet"}
_PY_TUPLE = {"tuple", "Tuple"}
_PY_ITER = {
    "Iterator", "Iterable", "Generator", "AsyncIterator", "AsyncIterable", "AsyncGenerator",
}


def _py(s: str) -> str:
    s = s.strip().strip("\"'")
    if not s:
        return "any"
    if s.startswith("typing."):
        s = s[len("typing."):]
    parts = _split_top(s, "|")
    if len(parts) > 1:
        non_none = [p for p in parts if p not in ("None", "NoneType")]
        if len(non_none) == 1 and len(parts) == 2:
            return f"option<{_py(non_none[0])}>"
        return "any"
    g = _generic(s, "[", "]")
    if g:
        base, args = g
        if base.startswith("typing."):
            base = base[len("typing."):]
        if base in _PY_LIST:
            return f"list<{_py(args[0])}>"
        if base in _PY_MAP:
            k = _py(args[0]) if args else "any"
            v = _py(args[1]) if len(args) > 1 else "any"
            return f"map<{k},{v}>"
        if base in _PY_SET:
            return f"set<{_py(args[0])}>"
        if base in _PY_TUPLE:
            return "tuple<" + ",".join(_py(a) for a in args) + ">"
        if base == "Optional":
            return f"option<{_py(args[0])}>"
        if base == "Union":
            non_none = [a for a in args if a not in ("None", "NoneType")]
            if len(non_none) == 1 and len(args) == 2:
                return f"option<{_py(non_none[0])}>"
            return "any"
        if base in _PY_ITER:
            return f"iter<{_py(args[0])}>"
        if base == "Callable":
            return "fn"
        if base in ("Awaitable", "Coroutine"):
            return _py(args[-1])
        return f"obj:{base.rsplit('.', 1)[-1]}"
    if s in _PY_SIMPLE:
        return _PY_SIMPLE[s]
    return f"obj:{s.rsplit('.', 1)[-1]}"


# ---------------------------------------------------------------- ts / js

_TS_SIMPLE = {
    "string": "str", "number": "f64", "boolean": "bool", "void": "unit",
    "undefined": "unit", "null": "unit", "any": "any", "unknown": "any",
    "never": "any", "object": "any", "bigint": "i64", "symbol": "any",
    "Function": "fn",
}


def _ts(s: str) -> str:
    s = s.strip()
    if not s:
        return "any"
    parts = _split_top(s, "|")
    if len(parts) > 1:
        non_null = [p for p in parts if p not in ("null", "undefined")]
        if not non_null:
            return "unit"
        if len(non_null) == 1 and len(parts) - len(non_null) >= 1:
            return f"option<{_ts(non_null[0])}>"
        return "any"
    if s.endswith("[]"):
        return f"list<{_ts(s[:-2])}>"
    g = _generic(s, "<", ">")
    if g:
        base, args = g
        if base in ("Array", "ReadonlyArray"):
            return f"list<{_ts(args[0])}>"
        if base in ("Record", "Map", "ReadonlyMap"):
            k = _ts(args[0]) if args else "any"
            v = _ts(args[1]) if len(args) > 1 else "any"
            return f"map<{k},{v}>"
        if base in ("Set", "ReadonlySet"):
            return f"set<{_ts(args[0])}>"
        if base == "Promise":
            return _ts(args[0])
        if base in ("Partial", "Required", "Readonly"):
            return _ts(args[0])
        return f"obj:{base}"
    if s in _TS_SIMPLE:
        return _TS_SIMPLE[s]
    return f"obj:{s}"


# ---------------------------------------------------------------- go

_GO_INT = {
    "int", "int8", "int16", "int32", "int64",
    "uint", "uint8", "uint16", "uint32", "uint64", "uintptr", "byte", "rune",
}


def _go(s: str | None) -> str:
    if s is None:
        return "unit"
    s = s.strip()
    if not s:
        return "unit"
    while s.startswith("*"):
        s = s[1:].strip()
    if s.startswith("..."):
        return f"list<{_go(s[3:])}>"
    if s == "[]byte":
        return "bytes"
    if s.startswith("[]"):
        return f"list<{_go(s[2:])}>"
    if s.startswith("map["):
        depth = 0
        for i, ch in enumerate(s[3:], start=3):
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    return f"map<{_go(s[4:i])},{_go(s[i + 1:])}>"
        return "map<any,any>"
    if s in ("interface{}", "any"):
        return "any"
    if s == "error":
        return "error"
    if s == "string":
        return "str"
    if s in _GO_INT:
        return "i64"
    if s in ("float32", "float64"):
        return "f64"
    if s == "bool":
        return "bool"
    if s.startswith("func"):
        return "fn"
    if s.startswith("chan ") or s.startswith("<-chan") or s.startswith("chan<-"):
        return f"obj:{s}"
    return f"obj:{s}"


def go_return(types: list[str]) -> str:
    """Fold a Go multi-return into one core-1 type."""
    if not types:
        return "unit"
    if len(types) == 1:
        return _go(types[0])
    if types[-1].strip() == "error":
        rest = types[:-1]
        ok = _go(rest[0]) if len(rest) == 1 else "tuple<" + ",".join(_go(t) for t in rest) + ">"
        return f"result<{ok},error>"
    return "tuple<" + ",".join(_go(t) for t in types) + ">"


# ---------------------------------------------------------------- rust

_RUST_INT = {
    "i8", "i16", "i32", "i64", "i128", "isize",
    "u8", "u16", "u32", "u64", "u128", "usize",
}
_RUST_WRAPPERS = {"Box", "Rc", "Arc", "Cell", "RefCell", "Mutex", "RwLock", "Pin"}


def _rust(s: str | None) -> str:
    if s is None:
        return "unit"
    s = s.strip()
    if not s or s == "()":
        return "unit"
    while s.startswith("&"):
        s = s[1:].strip()
        if s.startswith("mut "):
            s = s[4:].strip()
        if s.startswith("'"):  # lifetime
            s = s.split(None, 1)[1] if " " in s else ""
            s = s.strip()
    if not s:
        return "any"
    for prefix in ("dyn ", "impl "):
        if s.startswith(prefix):
            trait = s[len(prefix):].strip()
            base = trait.split("<")[0].split("(")[0].strip()
            if base in ("Fn", "FnMut", "FnOnce"):
                return "fn"
            return f"obj:{base}"
    if s.startswith(("Fn(", "FnMut(", "FnOnce(", "fn(")):
        return "fn"
    g = _generic(s, "<", ">")
    if g:
        base, args = g
        args = [a for a in args if not a.startswith("'")]  # drop lifetimes
        if base in _RUST_WRAPPERS:
            return _rust(args[0]) if args else "any"
        if base in ("Vec", "VecDeque"):
            return f"list<{_rust(args[0])}>"
        if base in ("HashMap", "BTreeMap"):
            k = _rust(args[0]) if args else "any"
            v = _rust(args[1]) if len(args) > 1 else "any"
            return f"map<{k},{v}>"
        if base in ("HashSet", "BTreeSet"):
            return f"set<{_rust(args[0])}>"
        if base == "Option":
            return f"option<{_rust(args[0])}>"
        if base == "Result":
            ok = _rust(args[0]) if args else "any"
            err = _rust(args[1]) if len(args) > 1 else "error"
            return f"result<{ok},{err}>"
        if base == "Cow":
            return _rust(args[0]) if args else "any"
        return f"obj:{base}"
    if s in ("String", "str", "char"):
        return "str"
    if s in _RUST_INT:
        return "i64"
    if s in ("f32", "f64"):
        return "f64"
    if s == "bool":
        return "bool"
    return f"obj:{s}"


# ---------------------------------------------------------------- entry

_LANG_FNS = {
    "python": _py,
    "javascript": _ts,
    "typescript": _ts,
    "tsx": _ts,
    "go": _go,
    "rust": _rust,
}


# A normalized core-1 type may only contain these characters. Anything the
# per-language mappers leak that violates this (multi-line real-world generics,
# lifetimes, stray fragments) is not a usable type → collapse to `any`.
_CORE1_ALLOWED = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_<>,:")


def _is_clean_core1(t: str) -> bool:
    return all(ch in _CORE1_ALLOWED for ch in t)


def normalize(raw: str | None, language: str) -> str:
    """Normalize a raw source-language type string into the core-1 vocabulary."""
    if language == "bash":
        return "str"
    fn = _LANG_FNS.get(language)
    if fn is None:
        return "any"
    if raw is None:
        # no annotation: dynamic languages → any; typed languages → unit (no return)
        return "any" if language in ("python", "javascript", "typescript", "tsx") else "unit"
    # collapse whitespace so multi-line real-world types normalize as one line
    result = fn(" ".join(raw.split()))
    # guard: any residue outside the core-1 grammar makes the type unusable downstream
    return result if _is_clean_core1(result) else "any"
