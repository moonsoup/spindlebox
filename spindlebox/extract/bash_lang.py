"""Bash extractor (tree-sitter walk).

Every bash function has the degenerate signature (args: list<str>) -> result<str,i64>
(argv in, stdout/exit-code out) — so all bash functions share one signature class
by design.
"""

from __future__ import annotations

from spindlebox.extract.base import RawDecl, RawParam
from spindlebox.extract.ts_util import parse, preceding_doc, text, walk

BASH_RETURN = "result<str,i64>"


def extract_bash_file(rel_path: str, source: str) -> list[RawDecl]:
    tree = parse("bash", source)
    root = tree.root_node
    fn_nodes = [n for n in walk(root) if n.type == "function_definition"]
    fn_names = {text(n.child_by_field_name("name")) for n in fn_nodes}

    imports = []
    for n in walk(root):
        if n.type == "command":
            name_node = n.child_by_field_name("name")
            if name_node is not None and text(name_node) in ("source", "."):
                args = [c for c in n.children if c.type in ("word", "string", "raw_string")]
                if args:
                    imports.append(text(args[-1]).strip("'\""))

    decls: list[RawDecl] = []
    for node in fn_nodes:
        name = text(node.child_by_field_name("name"))
        body = node.child_by_field_name("body") or node
        calls = []
        for n in walk(body):
            if n.type == "command":
                cname = n.child_by_field_name("name")
                if cname is not None and text(cname) in fn_names and text(cname) not in calls:
                    calls.append(text(cname))
        decls.append(RawDecl(
            name=name,
            kind="function",
            language="bash",
            file=rel_path,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            scope_chain=[],
            class_chain=[],
            params=[RawParam(name="args", kind="variadic")],
            returns_raw=None,
            returns_norm=BASH_RETURN,
            is_async=False,
            doc=preceding_doc(node, {"comment"}),
            body_text=text(node),
            calls=calls,
            imports=list(imports),
            state_capture="pure",
        ))
    return decls
