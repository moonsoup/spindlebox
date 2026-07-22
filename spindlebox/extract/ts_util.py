"""tree-sitter parser loading and node helpers shared by the non-Python extractors."""

from __future__ import annotations

from tree_sitter import Language, Node, Parser

_LANGS: dict[str, Language] = {}


def get_language(name: str) -> Language:
    if name in _LANGS:
        return _LANGS[name]
    if name == "javascript":
        import tree_sitter_javascript as mod
        lang = Language(mod.language())
    elif name == "typescript":
        import tree_sitter_typescript as mod
        lang = Language(mod.language_typescript())
    elif name == "tsx":
        import tree_sitter_typescript as mod
        lang = Language(mod.language_tsx())
    elif name == "go":
        import tree_sitter_go as mod
        lang = Language(mod.language())
    elif name == "rust":
        import tree_sitter_rust as mod
        lang = Language(mod.language())
    elif name == "bash":
        import tree_sitter_bash as mod
        lang = Language(mod.language())
    else:
        # declarative language profiles carry their own grammar spec
        import importlib

        from spindlebox.extract.profile_registry import grammar_for
        spec = grammar_for(name)
        if spec is None:
            raise ValueError(f"no tree-sitter grammar for '{name}'")
        mod = importlib.import_module(spec["module"])
        lang = Language(getattr(mod, spec["attr"])())
    _LANGS[name] = lang
    return lang


def parse(name: str, source: str):
    return Parser(get_language(name)).parse(source.encode("utf8"))


def text(node: Node | None) -> str:
    if node is None:
        return ""
    return node.text.decode("utf8", errors="replace")


def walk(node: Node):
    yield node
    for child in node.children:
        yield from walk(child)


def walk_own(node: Node, boundary_types: set[str]):
    """Walk a subtree without descending into nested scopes (boundary node types)."""
    for child in node.children:
        yield child
        if child.type not in boundary_types:
            yield from walk_own(child, boundary_types)


def first_line(comment: str) -> str:
    line = comment.strip()
    for prefix in ("///", "//!", "//", "#", "/*", "*"):
        if line.startswith(prefix):
            line = line[len(prefix):].strip()
            break
    return line.split("\n")[0].rstrip("*/ ").strip()


def preceding_doc(node: Node, comment_types: set[str] | None = None) -> str | None:
    """First line of the comment block immediately above a declaration."""
    comment_types = comment_types or {"comment", "line_comment", "block_comment"}
    prev = node.prev_named_sibling
    if prev is not None and prev.type in comment_types and prev.end_point[0] >= node.start_point[0] - 1:
        first = prev
        while (
            first.prev_named_sibling is not None
            and first.prev_named_sibling.type in comment_types
            and first.prev_named_sibling.end_point[0] == first.start_point[0] - 1
        ):
            first = first.prev_named_sibling
        return first_line(text(first)) or None
    return None
