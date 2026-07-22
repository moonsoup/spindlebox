"""Rust extractor (tree-sitter walk)."""

from __future__ import annotations

import re

from findexer.extract.base import RawDecl, RawParam
from findexer.extract.ts_util import parse, preceding_doc, text, walk, walk_own

_BOUNDARY = {"function_item", "closure_expression"}
_CALL_RE = re.compile(r"^[A-Za-z_][\w:]*(\.[\w]+)*$")


def _params(node) -> tuple[list[RawParam], str | None]:
    """Returns (params, self_kind) where self_kind is the self_parameter text if present."""
    plist = node.child_by_field_name("parameters")
    out: list[RawParam] = []
    self_kind = None
    if plist is None:
        return out, self_kind
    for pd in plist.named_children:
        if pd.type == "self_parameter":
            self_kind = text(pd)
            out.append(RawParam(name="self", raw_type=self_kind, kind="receiver"))
        elif pd.type == "parameter":
            pattern = pd.child_by_field_name("pattern")
            tp = pd.child_by_field_name("type")
            out.append(RawParam(
                name=text(pattern) if pattern is not None else f"arg{len(out)}",
                raw_type=text(tp) if tp is not None else None,
            ))
        elif pd.type == "identifier":  # untyped closure param
            out.append(RawParam(name=text(pd)))
    return out, self_kind


def _declared(node) -> set[str]:
    names: set[str] = set()
    plist = node.child_by_field_name("parameters")
    if plist is not None:
        names.update(text(n) for n in walk(plist) if n.type == "identifier")
    body = node.child_by_field_name("body")
    if body is None:
        return names
    for n in walk_own(body, _BOUNDARY):
        if n.type == "let_declaration":
            pattern = n.child_by_field_name("pattern")
            if pattern is not None:
                names.update(text(x) for x in walk(pattern) if x.type == "identifier")
    return names


def _writes(node) -> set[str]:
    body = node.child_by_field_name("body")
    targets: set[str] = set()
    if body is None:
        return targets
    for n in walk_own(body, _BOUNDARY):
        if n.type in ("assignment_expression", "compound_assignment_expr"):
            left = n.child_by_field_name("left")
            if left is not None and left.type == "identifier":
                targets.add(text(left))
    return targets


def _reads(node) -> set[str]:
    body = node.child_by_field_name("body")
    if body is None:
        return set()
    return {text(n) for n in walk_own(body, _BOUNDARY) if n.type == "identifier"}


def _calls(node) -> list[str]:
    body = node.child_by_field_name("body")
    calls: list[str] = []
    if body is None:
        return calls
    for n in walk_own(body, {"closure_expression"}):
        if n.type == "call_expression":
            fn = n.child_by_field_name("function")
            if fn is not None:
                t = text(fn)
                if _CALL_RE.match(t) and t not in calls:
                    calls.append(t.replace("::", "."))
    return calls


def _self_state(node, self_kind: str | None) -> str:
    if self_kind is None:
        return "pure"
    body = node.child_by_field_name("body")
    if body is not None:
        for n in walk_own(body, _BOUNDARY):
            if n.type in ("assignment_expression", "compound_assignment_expr"):
                left = n.child_by_field_name("left")
                if left is not None and text(left).startswith("self."):
                    return "mutates_instance"
    if "&mut" in self_kind:
        return "mutates_instance"
    if self_kind.strip() == "self":
        return "consumes"
    return "reads_instance"


def _is_async(node) -> bool:
    return any(c.type == "async" or text(c) == "async" for c in node.children
               if not c.is_named or c.type == "function_modifiers")


def extract_rust_file(rel_path: str, source: str) -> list[RawDecl]:
    tree = parse("rust", source)
    root = tree.root_node
    imports = [
        text(n.child_by_field_name("argument") or n)
        for n in walk(root) if n.type == "use_declaration"
    ]
    decls: list[RawDecl] = []

    def add(node, name, kind, scope, classes, params, state, returns_raw):
        decls.append(RawDecl(
            name=name,
            kind=kind,
            language="rust",
            file=rel_path,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            scope_chain=list(scope),
            class_chain=list(classes),
            params=params,
            returns_raw=returns_raw,
            is_async=_is_async(node),
            doc=preceding_doc(node, {"line_comment", "block_comment"}),
            body_text=text(node),
            calls=_calls(node),
            imports=list(imports),
            state_capture=state,
        ))

    def visit(node, scope, classes, anc_declared, in_func):
        for child in node.children:
            t = child.type
            if t == "impl_item":
                tp = child.child_by_field_name("type")
                type_name = text(tp).split("<")[0].strip() if tp is not None else "<impl>"
                visit(child, [*scope, type_name] if type_name not in scope else scope,
                      [*classes, type_name], anc_declared, in_func)
            elif t == "mod_item":
                mod_name = text(child.child_by_field_name("name"))
                visit(child, [*scope, mod_name], classes, anc_declared, in_func)
            elif t == "function_item":
                name = text(child.child_by_field_name("name"))
                params, self_kind = _params(child)
                rt = child.child_by_field_name("return_type")
                if self_kind is not None:
                    kind = "method"
                    state = _self_state(child, self_kind)
                elif in_func:
                    kind, state = "closure", "pure"
                else:
                    kind, state = ("method", "pure") if classes else ("function", "pure")
                add(child, name, kind, scope, classes, params, state,
                    text(rt) if rt is not None else None)
                visit(child, [*scope, name], classes, anc_declared | _declared(child), True)
            elif t == "closure_expression":
                own = _declared(child)
                writes = {w for w in _writes(child) if w not in own and w in anc_declared}
                reads = {r for r in _reads(child) if r not in own and r in anc_declared}
                moved = any(text(c) == "move" for c in child.children if not c.is_named)
                if writes:
                    state = "mutates_captured"
                elif moved:
                    state = "consumes"
                elif reads:
                    state = "reads_captured"
                else:
                    state = "pure"
                params, _ = _params(child)
                add(child, "<closure>", "closure", scope, classes, params, state, None)
                visit(child, scope, classes, anc_declared | own, True)
            else:
                visit(child, scope, classes, anc_declared, in_func)

    visit(root, [], [], set(), False)
    return decls
