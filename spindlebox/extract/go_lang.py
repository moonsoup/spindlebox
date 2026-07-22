"""Go extractor (tree-sitter walk)."""

from __future__ import annotations

import re

from spindlebox.extract.base import RawDecl, RawParam
from spindlebox.extract.ts_util import parse, preceding_doc, text, walk, walk_own
from spindlebox.typenorm import go_return

_BOUNDARY = {"func_literal", "function_declaration", "method_declaration"}
_CALL_RE = re.compile(r"^[A-Za-z_][\w]*(\.[\w]+)*$")


def _params(plist) -> list[RawParam]:
    out: list[RawParam] = []
    if plist is None:
        return out
    for pd in plist.named_children:
        if pd.type == "parameter_declaration":
            tp = text(pd.child_by_field_name("type"))
            names = [text(c) for c in pd.children if c.type == "identifier"]
            if not names:
                out.append(RawParam(name=f"arg{len(out)}", raw_type=tp))
            else:
                out.extend(RawParam(name=n, raw_type=tp) for n in names)
        elif pd.type == "variadic_parameter_declaration":
            tp = text(pd.child_by_field_name("type"))
            names = [text(c) for c in pd.children if c.type == "identifier"]
            out.append(RawParam(name=names[0] if names else "args", raw_type=tp, kind="variadic"))
    return out


def _result_types(node) -> list[str]:
    result = node.child_by_field_name("result")
    if result is None:
        return []
    if result.type == "parameter_list":
        types = []
        for pd in result.named_children:
            tp = pd.child_by_field_name("type")
            types.append(text(tp) if tp is not None else text(pd))
        return types
    return [text(result)]


def _declared(func_node) -> set[str]:
    names: set[str] = set()
    for field in ("parameters", "receiver"):
        p = func_node.child_by_field_name(field)
        if p is not None:
            names.update(text(n) for n in walk(p) if n.type == "identifier")
    body = func_node.child_by_field_name("body")
    if body is None:
        return names
    for n in walk_own(body, _BOUNDARY):
        if n.type == "short_var_declaration":
            left = n.child_by_field_name("left")
            if left is not None:
                names.update(text(x) for x in walk(left) if x.type == "identifier")
        elif n.type == "var_spec":
            names.update(
                text(c) for c in n.children if c.type == "identifier"
            )
        elif n.type == "range_clause":
            left = n.child_by_field_name("left")
            if left is not None:
                names.update(text(x) for x in walk(left) if x.type == "identifier")
    return names


def _writes(func_node) -> set[str]:
    body = func_node.child_by_field_name("body")
    targets: set[str] = set()
    if body is None:
        return targets
    for n in walk_own(body, _BOUNDARY):
        if n.type == "assignment_statement":
            left = n.child_by_field_name("left")
            if left is not None:
                targets.update(text(x) for x in walk(left) if x.type == "identifier")
        elif n.type in ("inc_statement", "dec_statement"):
            targets.update(text(x) for x in walk(n) if x.type == "identifier")
    return targets


def _calls(func_node) -> list[str]:
    body = func_node.child_by_field_name("body")
    calls: list[str] = []
    if body is None:
        return calls
    for n in walk_own(body, {"func_literal"}):
        if n.type == "call_expression":
            fn = n.child_by_field_name("function")
            if fn is not None:
                t = text(fn)
                if _CALL_RE.match(t) and t not in calls:
                    calls.append(t)
    return calls


def _receiver_state(func_node, recv_name: str) -> str:
    body = func_node.child_by_field_name("body")
    if body is None or not recv_name:
        return "pure"
    reads = False
    writes = _writes(func_node)
    for n in walk_own(body, {"func_literal"}):
        if n.type == "selector_expression":
            operand = n.child_by_field_name("operand")
            if operand is not None and text(operand) == recv_name:
                reads = True
    if recv_name in writes:
        return "mutates_instance"
    for n in walk_own(body, {"func_literal"}):
        if n.type == "assignment_statement":
            left = n.child_by_field_name("left")
            if left is not None and any(
                x.type == "selector_expression"
                and text(x.child_by_field_name("operand") or x) == recv_name
                for x in walk(left)
            ):
                return "mutates_instance"
    return "reads_instance" if reads else "pure"


def extract_go_file(rel_path: str, source: str) -> list[RawDecl]:
    tree = parse("go", source)
    root = tree.root_node
    imports = [
        text(n.child_by_field_name("path") or n).strip('"')
        for n in walk(root) if n.type == "import_spec"
    ]
    decls: list[RawDecl] = []

    def add(node, name, kind, scope, classes, params, state):
        types = _result_types(node)
        decls.append(RawDecl(
            name=name,
            kind=kind,
            language="go",
            file=rel_path,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            scope_chain=list(scope),
            class_chain=list(classes),
            params=params,
            returns_raw=text(node.child_by_field_name("result")) or None,
            returns_norm=go_return(types),
            is_async=False,
            doc=preceding_doc(node),
            body_text=text(node),
            calls=_calls(node),
            imports=list(imports),
            state_capture=state,
        ))

    def visit(node, scope, anc_declared):
        for child in node.children:
            if child.type == "function_declaration":
                name = text(child.child_by_field_name("name"))
                add(child, name, "function", scope, [], _params(
                    child.child_by_field_name("parameters")), "pure")
                visit(child, [*scope, name], anc_declared | _declared(child))
            elif child.type == "method_declaration":
                name = text(child.child_by_field_name("name"))
                recv = child.child_by_field_name("receiver")
                recv_name, recv_type = "", ""
                params = _params(child.child_by_field_name("parameters"))
                if recv is not None and recv.named_children:
                    pd = recv.named_children[0]
                    idents = [text(c) for c in pd.children if c.type == "identifier"]
                    recv_name = idents[0] if idents else ""
                    recv_type = text(pd.child_by_field_name("type")).lstrip("*")
                    params.insert(0, RawParam(
                        name=recv_name or "recv", raw_type=recv_type, kind="receiver"))
                add(child, name, "method", [recv_type] if recv_type else [],
                    [recv_type] if recv_type else [], params,
                    _receiver_state(child, recv_name))
                visit(child, [*scope, name], anc_declared | _declared(child))
            elif child.type == "func_literal":
                own = _declared(child)
                writes = {w for w in _writes(child) if w not in own and w in anc_declared}
                state = "mutates_captured" if writes else "reads_captured"
                add(child, "<closure>", "closure", scope, [],
                    _params(child.child_by_field_name("parameters")), state)
                visit(child, scope, anc_declared | own)
            else:
                visit(child, scope, anc_declared)

    visit(root, [], set())
    return decls
