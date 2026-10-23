"""Python extractor: stdlib ast + symtable (richer than tree-sitter for Python)."""

from __future__ import annotations

import ast
import builtins
import re
import symtable

from spindlebox.extract.base import RawDecl, RawFnTable, RawParam, RawType
from spindlebox.typenorm import normalize

_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)
_SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)

#: Every name Python provides without an import. Extraction marks calls to these
#: ``builtin:<name>`` so that no analysis module needs to know them (#37).
PY_BUILTINS = frozenset(dir(builtins))

#: Python's entry-point conventions, in the shape a profile's ``entry_points``
#: takes. These are exactly the names, prefixes and file rule ``gaps`` applied to
#: every language before #38; they now apply to Python alone.
PY_ENTRY_POINTS = {
    "names": ["main", "__init__", "__main__", "setup"],
    "prefixes": ["cmd_", "test_", "handle_"],
    "file_contains": ["test"],
}

#: Python's ``meta`` block, in the shape a profile's takes (#39). Every construct
#: is present; the native extractor reads the AST directly, so the specs only
#: carry what is data: the type spellings that mean "a callable".
PY_META = {
    "decorators": {"source": "decorator_list"},
    "parent": {},
    "takes_fn": {"fn_types": [r"\bCallable\b"]},
    "returns_fn": {"fn_types": [r"\bCallable\b"]},
    "param_calls": {},
    "table_calls": {},
}
_FN_TYPES = [re.compile(t) for t in PY_META["takes_fn"]["fn_types"]]


def _dotted(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return None


def _walk_own(node: ast.AST, *, skip_nested: bool = True):
    """Walk a function's own body, not descending into nested function scopes."""
    for child in ast.iter_child_nodes(node):
        if skip_nested and isinstance(child, _SCOPE_NODES):
            continue
        yield child
        yield from _walk_own(child, skip_nested=skip_nested)


def _collect_calls(func: ast.AST, param_names: set[str] | None = None) -> list[str]:
    """Called names in ``func``'s own body.

    With ``param_names`` (indexing with ``meta``), a call through a parameter is
    ``param:<name>`` and a call through a subscript, ``T[k](x)``, is
    ``table:<T>`` -- before #39 the second was silently dropped, because
    ``_dotted`` has no spelling for it. Without it the output is unchanged.
    """
    calls = []
    for n in _walk_own(func):
        if isinstance(n, ast.Call):
            name = _dotted(n.func)
            if param_names is not None:
                if isinstance(n.func, ast.Name) and name in param_names:
                    name = f"param:{name}"
                elif isinstance(n.func, ast.Subscript):
                    # T[k](x), and T[k]["fn"](x) through a table of records (#40)
                    base = n.func.value
                    while isinstance(base, ast.Subscript):
                        base = base.value
                    table = _dotted(base)
                    name = f"table:{table}" if table else None
            if name and name not in calls:
                calls.append(name)
    return calls


def _nested_defs(func: ast.AST):
    """The function and lambda nodes defined directly in ``func``'s own body."""
    for child in ast.iter_child_nodes(func):
        if isinstance(child, (*_FUNC_NODES, ast.Lambda)):
            yield child
        elif not isinstance(child, ast.ClassDef):
            yield from _nested_defs(child)


def _returns_fn(func: ast.AST) -> bool:
    """Is a callable returned: by annotation, or by handing back a nested function?"""
    if isinstance(func, ast.Lambda):
        return isinstance(func.body, ast.Lambda)
    if func.returns is not None and any(t.search(ast.unparse(func.returns)) for t in _FN_TYPES):
        return True
    nested = {d.name for d in _nested_defs(func) if not isinstance(d, ast.Lambda)}
    for n in _walk_own(func):
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Lambda):
            nested.update(t.id for t in n.targets if isinstance(t, ast.Name))
    for n in _walk_own(func):
        if isinstance(n, ast.Return) and n.value is not None:
            if isinstance(n.value, ast.Lambda):
                return True
            if isinstance(n.value, ast.Name) and n.value.id in nested:
                return True
    return False


def _self_name(func: ast.AST) -> str | None:
    args = func.args
    first = (args.posonlyargs + args.args)[:1]
    if first and first[0].arg in ("self", "cls"):
        return first[0].arg
    return None


def _instance_capture(func: ast.AST, self_name: str) -> str:
    reads = False
    for n in _walk_own(func):
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == self_name:
            if isinstance(n.ctx, ast.Store | ast.Del):
                return "mutates_instance"
            reads = True
    return "reads_instance" if reads else "pure"


def _global_writes(func: ast.AST) -> bool:
    declared: set[str] = set()
    for n in _walk_own(func):
        if isinstance(n, ast.Global):
            declared.update(n.names)
    if not declared:
        return False
    for n in _walk_own(func):
        if isinstance(n, ast.Name) and n.id in declared and isinstance(n.ctx, ast.Store):
            return True
    return False


def _symtable_functions(source: str, filename: str) -> dict[tuple[str, int], symtable.SymbolTable]:
    tables: dict[tuple[str, int], symtable.SymbolTable] = {}

    def walk(t: symtable.SymbolTable) -> None:
        for child in t.get_children():
            if child.get_type() == "function":
                tables[(child.get_name(), child.get_lineno())] = child
            walk(child)

    walk(symtable.symtable(source, filename, "exec"))
    return tables


def _params(func: ast.AST, is_method: bool) -> list[RawParam]:
    args = func.args
    params: list[RawParam] = []
    positional = args.posonlyargs + args.args
    defaults: list[str | None] = [None] * (len(positional) - len(args.defaults))
    defaults += [ast.unparse(d) for d in args.defaults]
    for i, (a, default) in enumerate(zip(positional, defaults, strict=True)):
        kind = "positional"
        if i == 0 and is_method and a.arg in ("self", "cls"):
            kind = "receiver"
        params.append(RawParam(
            name=a.arg,
            raw_type=ast.unparse(a.annotation) if a.annotation else None,
            default=default,
            kind=kind,
        ))
    if args.vararg:
        a = args.vararg
        params.append(RawParam(
            name=a.arg,
            raw_type=ast.unparse(a.annotation) if a.annotation else None,
            kind="variadic",
        ))
    for a, d in zip(args.kwonlyargs, args.kw_defaults, strict=True):
        params.append(RawParam(
            name=a.arg,
            raw_type=ast.unparse(a.annotation) if a.annotation else None,
            default=ast.unparse(d) if d else None,
            kind="keyword",
        ))
    if args.kwarg:
        params.append(RawParam(name=args.kwarg.arg, kind="kwvariadic"))
    return params


def extract_python_file(rel_path: str, source: str, meta: bool = False) -> list[RawDecl]:
    """``meta`` adds what #39 records about functions used as values (decorators,
    parent, takes_fn, returns_fn, ``param:``/``table:`` calls); the default
    output is unchanged."""
    tree = ast.parse(source)
    try:
        func_tables = _symtable_functions(source, rel_path)
    except (SyntaxError, ValueError):
        func_tables = {}

    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imports.append(node.module)

    def scope_chains(node: ast.AST) -> tuple[list[str], list[str], ast.AST | None]:
        """(full scope chain, class-only chain, nearest scope ancestor)."""
        chain: list[str] = []
        classes: list[str] = []
        nearest: ast.AST | None = None
        p = parents.get(node)
        while p is not None:
            if isinstance(p, _SCOPE_NODES):
                if nearest is None:
                    nearest = p
                if isinstance(p, ast.ClassDef):
                    chain.append(p.name)
                    classes.append(p.name)
                elif isinstance(p, ast.Lambda):
                    chain.append(f"lambda{p.lineno}")
                else:
                    chain.append(p.name)
            p = parents.get(p)
        chain.reverse()
        classes.reverse()
        return chain, classes, nearest

    def enclosing_funcs(node: ast.AST):
        """Function and lambda nodes enclosing ``node``, innermost first."""
        p = parents.get(node)
        while p is not None:
            if isinstance(p, (*_FUNC_NODES, ast.Lambda)):
                yield p
            p = parents.get(p)

    def local_names(func: ast.AST) -> set[str]:
        table = func_tables.get(
            ("lambda" if isinstance(func, ast.Lambda) else func.name, func.lineno))
        return set(table.get_locals()) if table else set()

    decl_of: dict[ast.AST, RawDecl] = {}
    decls: list[RawDecl] = []
    for node in ast.walk(tree):
        if not isinstance(node, (*_FUNC_NODES, ast.Lambda)):
            continue
        chain, classes, nearest = scope_chains(node)
        is_lambda = isinstance(node, ast.Lambda)
        if is_lambda:
            kind = "lambda"
            name = "<lambda>"
        elif isinstance(nearest, ast.ClassDef):
            kind = "method"
            name = node.name
        elif nearest is not None:
            kind = "closure"
            name = node.name
        else:
            kind = "function"
            name = node.name

        if kind == "method":
            self_name = _self_name(node)
            state = _instance_capture(node, self_name) if self_name else "pure"
        else:
            table = func_tables.get(("lambda" if is_lambda else name, node.lineno))
            nonlocals = set(table.get_nonlocals()) if table else set()
            frees = set(table.get_frees()) if table else set()
            if nonlocals:
                state = "mutates_captured"
            elif _global_writes(node) if not is_lambda else False:
                state = "mutates_captured"
            elif frees:
                state = "reads_captured"
            else:
                state = "pure"

        params = _params(node, kind == "method")
        param_names = {p.name for p in params if p.kind != "receiver"} if meta else None
        calls = _collect_calls(node, param_names)
        decl = RawDecl(
            name=name,
            kind=kind,
            language="python",
            file=rel_path,
            start_line=node.lineno,
            end_line=getattr(node, "end_lineno", node.lineno),
            scope_chain=chain,
            class_chain=classes,
            params=params,
            returns_raw=(
                ast.unparse(node.returns) if not is_lambda and node.returns else None
            ),
            is_async=isinstance(node, ast.AsyncFunctionDef),
            doc=(
                (ast.get_docstring(node) or "").strip().splitlines()[0]
                if not is_lambda and ast.get_docstring(node)
                else None
            ),
            body_text=ast.get_source_segment(source, node) or "",
            calls=calls,
            imports=list(imports),
            state_capture=state,
        )
        if meta:
            receiver = next((p.name for p in params if p.kind == "receiver"), None)
            for call in calls:
                if not call.startswith("table:"):
                    continue
                root = call[len("table:"):].split(".", 1)[0]
                if root == receiver:
                    decl.table_scopes[call] = ("receiver", None)
                elif root in local_names(node):
                    decl.table_scopes[call] = ("item", decl)
                else:
                    owner = next((f for f in enclosing_funcs(node) if root in local_names(f)), None)
                    # enclosing functions are walked (and recorded) before nested ones
                    decl.table_scopes[call] = (
                        ("item", decl_of[owner]) if owner in decl_of else ("module", None))
            parent = next(enclosing_funcs(node), None)
            decl.parent = decl_of.get(parent) if parent is not None else None
            if not is_lambda:
                decl.decorators = [ast.unparse(d) for d in node.decorator_list]
            decl.takes_fn = any(
                p.raw_type and any(t.search(p.raw_type) for t in _FN_TYPES) for p in params
            ) or any(c.startswith("param:") for c in calls)
            decl.returns_fn = _returns_fn(node)
        decl_of[node] = decl
        decls.append(decl)
    return decls


# ------------------------------------------------- functions held in data (#40)

#: Python's ``fn_tables`` spec, in the shape a profile's takes (#40). The native
#: extractor reads the AST directly, so this records what it detects rather
#: than how: module- and class-level literals, registries filled by
#: ``T[k] = fn`` / ``T.append(fn)`` / ``T.add(fn)`` (directly, or inside a
#: function called with or decorating the function), and the entry points a
#: ``pyproject.toml`` declares.
PY_FN_TABLES = {
    "source": "ast",
    "literals": ["dict", "list", "tuple", "set"],
    "registries": ["T[k] = fn", "T.append(fn)", "T.add(fn)"],
    "entry_points": "pyproject.toml",
}

#: Methods that put their argument into a table, and the key it is then found by.
_STORE_METHODS = {"append": "int", "add": None}


def _fn_refs(node: ast.AST) -> list[str]:
    """Names a table entry holds: ``f``, ``mod.f``, or those inside a nested record."""
    if isinstance(node, ast.Name | ast.Attribute):
        name = _dotted(node)
        return [name] if name else []
    if isinstance(node, ast.Dict):
        return [r for v in node.values for r in _fn_refs(v)]
    if isinstance(node, ast.Tuple | ast.List | ast.Set):
        return [r for e in node.elts for r in _fn_refs(e)]
    return []


def _const_key_type(key: ast.AST | None) -> str:
    if isinstance(key, ast.Constant) and isinstance(key.value, str):
        return "str"
    if isinstance(key, ast.Constant) and type(key.value) is int:
        return "int"
    return "any"


def _literal_table(value: ast.AST) -> tuple[str, str | None, list[str]] | None:
    """(kind, key_type, member names) when ``value`` is a dict/list/tuple/set literal."""
    if isinstance(value, ast.Dict):
        types = {_const_key_type(k) for k in value.keys}
        key_type = types.pop() if len(types) == 1 else "any"
        return "dict", key_type, [r for v in value.values for r in _fn_refs(v)]
    if isinstance(value, ast.List | ast.Tuple):
        return "list", "int", [r for e in value.elts for r in _fn_refs(e)]
    if isinstance(value, ast.Set):
        return "list", None, [r for e in value.elts for r in _fn_refs(e)]
    return None


def _store(stmt: ast.AST, tables: set[str]) -> tuple[str, ast.AST, str | None, ast.AST | None] | None:
    """``(table, stored value, key_type, key node)`` when ``stmt`` puts a value
    into one of ``tables``: ``T[k] = v``, ``T.append(v)`` or ``T.add(v)``."""
    if isinstance(stmt, ast.Assign):
        for t in stmt.targets:
            if isinstance(t, ast.Subscript) and _dotted(t.value) in tables:
                return _dotted(t.value), stmt.value, _const_key_type(t.slice), t.slice
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
        call = stmt.value
        f = call.func
        if (isinstance(f, ast.Attribute) and f.attr in _STORE_METHODS
                and _dotted(f.value) in tables and len(call.args) == 1):
            return _dotted(f.value), call.args[0], _STORE_METHODS[f.attr], None
    return None


def _positional(func: ast.AST) -> list[ast.arg]:
    return func.args.posonlyargs + func.args.args


def _registrar(func: ast.FunctionDef, module_names: set[str]) -> dict | None:
    """How ``func`` puts a function into a module-level table, or None.

    ``direct``: a parameter of ``func`` itself is stored (``register(fn)``, or a
    plain ``@register`` decorator). ``factory``: a parameter of a function nested
    in it is stored (``@register("name")``). The key annotation, when the key is a
    parameter, types the table's keys.
    """
    annotations = {}
    for g in [func, *(n for n in ast.walk(func) if isinstance(n, _FUNC_NODES) and n is not func)]:
        params = {a.arg: a for a in _positional(g) + g.args.kwonlyargs}
        for a in params.values():
            if a.annotation is not None:
                annotations.setdefault(a.arg, ast.unparse(a.annotation))
        for n in _walk_own(g):
            found = _store(n, module_names)
            if found is None:
                continue
            table, value, key_type, key = found
            stored = [r for r in _fn_refs(value) if r in params]
            if not stored:
                continue
            if isinstance(key, ast.Name):
                raw = annotations.get(key.id)
                key_type = normalize(raw, "python") if raw else "any"
            names = [a.arg for a in _positional(g)]
            return {
                "name": func.name, "table": table,
                "mode": "direct" if g is func else "factory",
                "param": stored[0],
                "index": names.index(stored[0]) if stored[0] in names else None,
                "key_type": key_type,
            }
    return None


def extract_python_fn_tables(rel_path: str, source: str,
                             decls: list[RawDecl] | None = None) -> dict:
    """The data structures in one file that hold functions (#40).

    Returns ``{"tables": [RawFnTable], "registrars": [...], "registrations": [...]}``.
    Tables are module- and class-level literals plus module-level stores into
    them; their members are names as written. A *registrar* is a module-level
    function that stores a function into a module-level table; a *registration*
    is a decorator, or a module-level call, that may hand it one. Registrars and registrations
    can sit in different files, so ``build_index`` pairs them. ``decls`` are this
    file's items, so a decorated function can be named by its ``RawDecl``.
    """
    tree = ast.parse(source)
    by_line = {(d.start_line, d.name): d for d in decls or []}
    tables: dict[str, RawFnTable] = {}

    def scan(body: list[ast.stmt], chain: list[str]) -> None:
        for stmt in body:
            if isinstance(stmt, ast.ClassDef):
                scan(stmt.body, [*chain, stmt.name])
                continue
            target = None
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                target = stmt.targets[0]
            elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
                target = stmt.target
            if isinstance(target, ast.Name):
                lit = _literal_table(stmt.value)
                if lit is not None:
                    kind, key_type, refs = lit
                    key = ".".join([*chain, target.id])
                    tables[key] = RawFnTable(
                        name=target.id, file=rel_path, start_line=stmt.lineno,
                        end_line=stmt.end_lineno or stmt.lineno, kind=kind,
                        key_type=key_type, members=refs, scope_chain=list(chain))
                continue
            if chain:
                continue
            found = _store(stmt, {k for k in tables if "." not in k})
            if found is not None:
                name, value, key_type, _ = found
                t = tables[name]
                refs = _fn_refs(value)
                if refs and not t.members:
                    t.kind, t.key_type = "registry", key_type
                t.members.extend(refs)

    scan(tree.body, [])
    module_names = {k for k in tables if "." not in k}
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign | ast.AnnAssign):
            targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
            module_names.update(t.id for t in targets if isinstance(t, ast.Name))

    registrars = []
    for stmt in tree.body:
        if isinstance(stmt, _FUNC_NODES):
            r = _registrar(stmt, module_names)
            if r is not None:
                assigned = tables.get(r["table"])
                r.update(file=rel_path, start_line=assigned.start_line if assigned else stmt.lineno,
                         end_line=assigned.end_line if assigned else stmt.end_lineno)
                registrars.append(r)

    registrations = []
    for node in ast.walk(tree):
        if isinstance(node, _FUNC_NODES):
            decl = by_line.get((node.lineno, node.name))
            for d in node.decorator_list:
                head = _dotted(d.func if isinstance(d, ast.Call) else d)
                if head and decl is not None:
                    registrations.append({
                        "head": head, "mode": "factory" if isinstance(d, ast.Call) else "direct",
                        "member": decl, "file": rel_path, "line": node.lineno})
    # register(fn) at module level only: inside a function its argument is
    # usually a parameter or local, which no name lookup can resolve safely
    for node in _walk_own(tree):
        if isinstance(node, ast.Call):
            head = _dotted(node.func)
            if head:
                registrations.append({
                    "head": head, "mode": "call", "file": rel_path, "line": node.lineno,
                    "args": [_dotted(a) if isinstance(a, ast.Name | ast.Attribute) else None
                             for a in node.args],
                    "kwargs": {k.arg: _dotted(k.value) for k in node.keywords
                               if k.arg and isinstance(k.value, ast.Name | ast.Attribute)},
                })
    return {"tables": list(tables.values()), "registrars": registrars,
            "registrations": registrations}


def _toml_header(line: str) -> list[str] | None:
    s = line.strip()
    if not s.startswith("[") or s.startswith("[["):
        return None
    inner = s[1:s.index("]")] if "]" in s else s[1:]
    return [a or b or c for a, b, c in
            re.findall(r'"([^"]*)"|\'([^\']*)\'|([^.\s"\']+)', inner)]


def _toml_span(lines: list[str], path: list[str]) -> tuple[int, int]:
    for i, line in enumerate(lines):
        if _toml_header(line) == path:
            end = i
            for j in range(i + 1, len(lines)):
                if _toml_header(lines[j]) is not None:
                    break
                if lines[j].strip() and not lines[j].strip().startswith("#"):
                    end = j
            return i + 1, end + 1
    return 1, max(len(lines), 1)


def pyproject_fn_tables(text: str, rel_path: str = "pyproject.toml") -> list[RawFnTable]:
    """The entry points a ``pyproject.toml`` declares, one table per group (#40):
    ``[project.scripts]``, ``[project.gui-scripts]`` and each
    ``[project.entry-points.<group>]``. Members are ``module.attr`` paths."""
    import tomllib
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return []
    project = data.get("project")
    if not isinstance(project, dict):
        return []
    groups = [(["project", k], project[k]) for k in ("scripts", "gui-scripts")
              if isinstance(project.get(k), dict)]
    eps = project.get("entry-points")
    if isinstance(eps, dict):
        groups += [(["project", "entry-points", g], v) for g, v in eps.items()
                   if isinstance(v, dict)]
    lines = text.splitlines()
    out = []
    for path, entries in groups:
        refs = []
        for value in entries.values():
            if not isinstance(value, str):
                continue
            module, _, attr = value.split("[", 1)[0].strip().partition(":")
            refs.append(f"{module.strip()}.{attr.strip()}" if attr.strip() else module.strip())
        start, end = _toml_span(lines, path)
        out.append(RawFnTable(
            name=path[-1], file=rel_path, start_line=start, end_line=end,
            kind="entry_points", key_type="str", members=refs, qualified=True,
            address=".".join(["pyproject", *path])))
    return out


# ------------------------------------------------------- data structures (#44)

#: Python's ``datatypes`` block, in the shape a profile's takes: which spellings
#: declare a record or an enum. Matched on the last dotted segment.
PY_DATATYPES = {
    "record_decorators": ["dataclass", "define", "frozen", "mutable", "s", "attrs"],
    "record_bases": ["NamedTuple", "TypedDict", "BaseModel"],
    "enum_bases": ["Enum", "IntEnum", "StrEnum", "Flag", "IntFlag"],
    "generic_bases": ["Generic", "Protocol"],
}


def _last(node: ast.AST) -> str | None:
    d = _dotted(node.func if isinstance(node, ast.Call) else node)
    return d.rsplit(".", 1)[-1] if d else None


def _class_type_params(cls: ast.ClassDef) -> list[str]:
    params = [p.name for p in getattr(cls, "type_params", ()) or ()]   # PEP 695
    for base in cls.bases:
        if isinstance(base, ast.Subscript) and _last(base.value) in PY_DATATYPES["generic_bases"]:
            sl = base.slice
            for e in (sl.elts if isinstance(sl, ast.Tuple) else [sl]):
                if isinstance(e, ast.Name) and e.id not in params:
                    params.append(e.id)
    return params


def _union_members(value: ast.AST) -> list[str] | None:
    """``A | B | C`` or ``Union[A, B, C]`` -> the names, when every operand is a
    plain or dotted name (and not ``None``); else None."""
    if isinstance(value, ast.BinOp) and isinstance(value.op, ast.BitOr):
        left, right = _union_members(value.left), _union_members(value.right)
        return left + right if left is not None and right is not None else None
    if isinstance(value, ast.Subscript) and _last(value.value) == "Union":
        sl = value.slice
        out: list[str] = []
        for e in (sl.elts if isinstance(sl, ast.Tuple) else [sl]):
            m = _union_members(e)
            if m is None:
                return None
            out += m
        return out
    d = _dotted(value)
    if d is None or d == "None":
        return None
    return [d.rsplit(".", 1)[-1]]


def extract_python_types(rel_path: str, source: str) -> list[RawType]:
    """Records, enums and unions declared at module or class level (#44).

    A record is a class with a record decorator or base (``PY_DATATYPES``); its
    fields are its annotated class attributes, ``ClassVar`` excluded. An enum is a
    class with an enum base; its variants are its assigned names. A union is a
    module-level alias of two or more names joined by ``|`` or ``Union[...]``
    (``Payment = Card | Transfer | Cash``); since that is also how a bit mask is
    spelled, it is ``strict`` and kept only if every member is a record.
    """
    tree = ast.parse(source, filename=rel_path)
    out: list[RawType] = []

    def segment(node: ast.AST | None) -> str | None:
        if node is None:
            return None
        return ast.get_source_segment(source, node) or ast.unparse(node)

    def visit(body: list[ast.stmt], scope: list[str]) -> None:
        for node in body:
            if isinstance(node, ast.ClassDef):
                base_names = {_last(b.value if isinstance(b, ast.Subscript) else b)
                              for b in node.bases}
                decos = {_last(d) for d in node.decorator_list}
                common = dict(name=node.name, file=rel_path, start_line=node.lineno,
                              end_line=node.end_lineno or node.lineno, language="python",
                              type_params=_class_type_params(node), scope_chain=list(scope))
                if base_names & set(PY_DATATYPES["enum_bases"]):
                    names = [t.id for st in node.body if isinstance(st, ast.Assign)
                             for t in st.targets
                             if isinstance(t, ast.Name) and not t.id.startswith("_")]
                    out.append(RawType(kind="variant", variants=[(n, []) for n in names],
                                       **common))
                elif (decos & set(PY_DATATYPES["record_decorators"])
                      or base_names & set(PY_DATATYPES["record_bases"])):
                    fields = [(st.target.id, segment(st.annotation)) for st in node.body
                              if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name)
                              and "ClassVar" not in (segment(st.annotation) or "")]
                    out.append(RawType(kind="record", fields=fields, **common))
                visit(node.body, [*scope, node.name])
            elif not scope and isinstance(node, ast.Assign | ast.AnnAssign):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if len(targets) != 1 or not isinstance(targets[0], ast.Name) or node.value is None:
                    continue
                members = _union_members(node.value)
                if members is None or len(members) < 2:
                    continue
                out.append(RawType(
                    name=targets[0].id, kind="variant", file=rel_path, start_line=node.lineno,
                    end_line=node.end_lineno or node.lineno, language="python",
                    variants=[(m, None) for m in members], strict=True))
            elif not scope and type(node).__name__ == "TypeAlias":    # PEP 695 `type X = ...`
                members = _union_members(node.value)
                if members is not None and len(members) >= 2:
                    out.append(RawType(
                        name=node.name.id, kind="variant", file=rel_path, start_line=node.lineno,
                        end_line=node.end_lineno or node.lineno, language="python",
                        variants=[(m, None) for m in members], strict=True))

    visit(tree.body, [])
    return out
