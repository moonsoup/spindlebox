"""JavaScript / TypeScript extractor (tree-sitter walk)."""

from __future__ import annotations

import re

from findexer.extract.base import RawDecl, RawParam
from findexer.extract.ts_util import parse, preceding_doc, text, walk, walk_own

FUNC_TYPES = {
    "function_declaration", "generator_function_declaration", "function_expression",
    "generator_function", "arrow_function", "method_definition",
}
CLASS_TYPES = {"class_declaration", "class"}
BOUNDARIES = FUNC_TYPES | CLASS_TYPES
_CALL_RE = re.compile(r"^[A-Za-z_$][\w$]*(\.[\w$]+)*$")


def _collect_imports(root) -> list[str]:
    imports = []
    for n in walk(root):
        if n.type == "import_statement":
            src = n.child_by_field_name("source")
            if src is not None:
                imports.append(text(src).strip("'\""))
        elif n.type == "call_expression":
            fn = n.child_by_field_name("function")
            if fn is not None and text(fn) == "require":
                args = n.child_by_field_name("arguments")
                if args is not None and args.named_children:
                    imports.append(text(args.named_children[0]).strip("'\""))
    return imports


def _declared_names(func_node) -> set[str]:
    names: set[str] = set()
    for field in ("parameters", "parameter"):
        p = func_node.child_by_field_name(field)
        if p is not None:
            names.update(text(n) for n in walk(p) if n.type == "identifier")
    body = func_node.child_by_field_name("body") or func_node
    for n in walk_own(body, FUNC_TYPES):
        if n.type == "variable_declarator":
            nm = n.child_by_field_name("name")
            if nm is not None:
                names.update(
                    text(x) for x in walk(nm)
                    if x.type in ("identifier", "shorthand_property_identifier_pattern")
                )
        elif n.type == "function_declaration":
            nm = n.child_by_field_name("name")
            if nm is not None:
                names.add(text(nm))
    return names


def _params(func_node) -> list[RawParam]:
    plist = func_node.child_by_field_name("parameters")
    if plist is None:
        single = func_node.child_by_field_name("parameter")
        if single is not None:
            return [RawParam(name=text(single))]
        return []
    out: list[RawParam] = []
    for i, node in enumerate(plist.named_children):
        t = node.type
        raw_type = None
        default = None
        kind = "positional"
        target = node
        if t in ("required_parameter", "optional_parameter"):
            tp = node.child_by_field_name("type")
            if tp is not None:
                raw_type = text(tp).lstrip(":").strip()
            val = node.child_by_field_name("value")
            if val is not None:
                default = text(val)
            target = node.child_by_field_name("pattern") or node
            t = target.type
        if t == "assignment_pattern":
            left = target.child_by_field_name("left")
            default = text(target.child_by_field_name("right"))
            target = left if left is not None else target
            t = target.type if target is not None else "identifier"
        if t == "rest_pattern":
            kind = "variadic"
            idents = [c for c in walk(target) if c.type == "identifier"]
            name = text(idents[0]) if idents else f"arg{i}"
        elif t == "identifier":
            name = text(target)
        elif t == "this":
            name = "this"
            kind = "receiver"
        else:  # object/array destructuring
            name = f"arg{i}"
        out.append(RawParam(name=name, raw_type=raw_type, default=default, kind=kind))
    return out


def _name_for(node) -> str | None:
    nm = node.child_by_field_name("name")
    if nm is not None:
        return text(nm)
    parent = node.parent
    if parent is not None:
        if parent.type == "variable_declarator":
            pn = parent.child_by_field_name("name")
            if pn is not None and pn.type == "identifier":
                return text(pn)
        elif parent.type == "pair":
            return text(parent.child_by_field_name("key"))
        elif parent.type == "assignment_expression":
            left = text(parent.child_by_field_name("left"))
            if _CALL_RE.match(left):
                return left.rsplit(".", 1)[-1]
    return None


def _writes(func_node) -> set[str]:
    body = func_node.child_by_field_name("body") or func_node
    targets: set[str] = set()
    for n in walk_own(body, FUNC_TYPES):
        if n.type in ("assignment_expression", "augmented_assignment_expression"):
            left = n.child_by_field_name("left")
            if left is not None and left.type == "identifier":
                targets.add(text(left))
        elif n.type == "update_expression":
            arg = n.child_by_field_name("argument")
            if arg is not None and arg.type == "identifier":
                targets.add(text(arg))
    return targets


def _reads(func_node) -> set[str]:
    body = func_node.child_by_field_name("body") or func_node
    return {text(n) for n in walk_own(body, FUNC_TYPES) if n.type == "identifier"}


def _this_capture(func_node) -> str:
    body = func_node.child_by_field_name("body") or func_node
    reads = False
    for n in walk_own(body, FUNC_TYPES):
        if n.type in ("assignment_expression", "augmented_assignment_expression"):
            left = n.child_by_field_name("left")
            if left is not None and text(left).startswith("this."):
                return "mutates_instance"
        elif n.type == "update_expression":
            arg = n.child_by_field_name("argument")
            if arg is not None and text(arg).startswith("this."):
                return "mutates_instance"
        elif n.type == "this":
            reads = True
    return "reads_instance" if reads else "pure"


def _calls(func_node) -> list[str]:
    body = func_node.child_by_field_name("body") or func_node
    calls: list[str] = []
    for n in walk_own(body, FUNC_TYPES):
        if n.type == "call_expression":
            fn = n.child_by_field_name("function")
            if fn is not None:
                t = text(fn)
                if _CALL_RE.match(t) and t not in calls:
                    calls.append(t)
    return calls


def _doc_for(node) -> str | None:
    doc = preceding_doc(node)
    if doc:
        return doc
    # arrow/function assigned to a declaration: comment sits above the statement
    p = node.parent
    hops = 0
    while p is not None and hops < 4:
        if p.type in ("lexical_declaration", "variable_declaration", "export_statement",
                      "expression_statement"):
            return preceding_doc(p)
        p = p.parent
        hops += 1
    return None


def _is_async(node) -> bool:
    return any(c.type == "async" for c in node.children)


def extract_js_file(rel_path: str, source: str, language: str) -> list[RawDecl]:
    grammar = "tsx" if rel_path.endswith(".tsx") else (
        "typescript" if language == "typescript" else "javascript"
    )
    tree = parse(grammar, source)
    root = tree.root_node
    imports = _collect_imports(root)
    module_declared = {
        text(n.child_by_field_name("name") or n)
        for n in walk_own(root, BOUNDARIES)
        if n.type == "variable_declarator"
    }
    decls: list[RawDecl] = []

    def handle(node, scope, classes, anc_declared, in_func):
        name = _name_for(node)
        anonymous = name is None
        if node.type == "method_definition" and classes:
            kind = "method"
        elif anonymous:
            kind = "lambda" if node.type == "arrow_function" else "closure"
        elif in_func:
            kind = "closure"
        else:
            kind = "function"
        name = name or "<anonymous>"

        if kind == "method":
            state = _this_capture(node)
        else:
            own = _declared_names(node)
            writes = {w for w in _writes(node) if w not in own and w in anc_declared}
            reads = {r for r in _reads(node) if r not in own and r in anc_declared}
            if writes:
                state = "mutates_captured"
            elif reads and (in_func or kind in ("closure", "lambda")):
                state = "reads_captured"
            else:
                state = "pure"

        rt = node.child_by_field_name("return_type")
        decls.append(RawDecl(
            name=name,
            kind=kind,
            language=language,
            file=rel_path,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            scope_chain=list(scope),
            class_chain=list(classes),
            params=_params(node),
            returns_raw=text(rt).lstrip(":").strip() if rt is not None else None,
            is_async=_is_async(node),
            doc=_doc_for(node),
            body_text=text(node),
            calls=_calls(node),
            imports=list(imports),
            state_capture=state,
        ))
        child_anc = anc_declared | _declared_names(node)
        visit(node, [*scope, name if not anonymous else f"anon{node.start_point[0] + 1}"],
              classes, child_anc, True)

    def visit(node, scope, classes, anc_declared, in_func):
        for child in node.children:
            t = child.type
            if t in CLASS_TYPES:
                cname = text(child.child_by_field_name("name")) or "<class>"
                visit(child, [*scope, cname], [*classes, cname], anc_declared, in_func)
            elif t in FUNC_TYPES:
                handle(child, scope, classes, anc_declared, in_func)
            else:
                visit(child, scope, classes, anc_declared, in_func)

    visit(root, [], [], set(module_declared), False)
    return decls
