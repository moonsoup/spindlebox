"""Python extractor: stdlib ast + symtable (richer than tree-sitter for Python)."""

from __future__ import annotations

import ast
import symtable

from spindlebox.extract.base import RawDecl, RawParam

_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)
_SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


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


def _collect_calls(func: ast.AST) -> list[str]:
    calls = []
    for n in _walk_own(func):
        if isinstance(n, ast.Call):
            name = _dotted(n.func)
            if name and name not in calls:
                calls.append(name)
    return calls


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
            if isinstance(n.ctx, (ast.Store, ast.Del)):
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


def extract_python_file(rel_path: str, source: str) -> list[RawDecl]:
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

        decls.append(RawDecl(
            name=name,
            kind=kind,
            language="python",
            file=rel_path,
            start_line=node.lineno,
            end_line=getattr(node, "end_lineno", node.lineno),
            scope_chain=chain,
            class_chain=classes,
            params=_params(node, kind == "method"),
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
            calls=_collect_calls(node),
            imports=list(imports),
            state_capture=state,
        ))
    return decls
