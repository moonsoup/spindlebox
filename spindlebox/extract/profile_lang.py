"""Generic profile-driven extractor: one tree-sitter walk for any language.

The walk is parameterized entirely by a ``LanguageProfile`` (JSON data).
The few behaviors that resist declarative description live in the HOOKS
library below and are referenced from profiles *by name* — adding a new
language should not normally require adding a hook.
"""

from __future__ import annotations

import re

from spindlebox.extract.base import RawDecl, RawFnTable, RawParam, RawType
from spindlebox.extract.profile_registry import (
    CONSTRUCTS,
    LanguageProfile,
    datatypes_for,
    fn_tables_for,
    meta_spec,
)
from spindlebox.extract.ts_util import parse, preceding_doc, text, walk, walk_own

HOOKS: dict = {}


def hook(name: str):
    def register(fn):
        HOOKS[name] = fn
        return fn
    return register


# ------------------------------------------------------------------ helpers

def _clean_doc(doc: str | None, style: str | None) -> str | None:
    if doc and style == "javadoc":
        doc = doc.lstrip("*").strip() or None
    return doc


def _field_or_self(node, field_name: str | None):
    if field_name is None:
        return node
    return node.child_by_field_name(field_name) or node


#: A name a table call can be addressed by: ``T``, ``self.routes``, ``a.b.c``.
_DOTTED = re.compile(r"^[A-Za-z_$][\w$]*(\.[\w$]+)*$")


def _dotted_name(raw: str) -> str | None:
    """``a->b``, ``a::b`` and ``a.b`` all spell the dotted name ``a.b``."""
    name = raw.replace("->", ".").replace("::", ".")
    return name if _DOTTED.match(name) else None


class ProfileWalker:
    def __init__(self, profile: LanguageProfile, rel_path: str, source: str,
                 meta: bool = False):
        self.p = profile
        self.rel_path = rel_path
        # functions used as values (#39): off by default so the walker's output
        # stays exactly the legacy extractors' (test_profile_walker); indexing
        # turns it on
        self.meta = meta
        self.meta_specs = {c: meta_spec(profile.language, c)
                           for c in CONSTRUCTS} if meta else {}
        self._emitted: dict[int, tuple[RawDecl, object]] = {}
        self._module_names: set[str] | None = None
        source_hook = profile.raw.get("source_hook")
        if source_hook:
            # A spelling the grammar genuinely cannot parse, blanked before the
            # parse. The fixup MUST preserve length: every span, line number and
            # column in the index has to keep pointing at the file on disk. A
            # fixup that does not is discarded rather than trusted.
            fixed = HOOKS[source_hook](source)
            source = fixed if len(fixed) == len(source) else source
        self.source = source
        self.boundaries = set(profile.boundaries)
        self.decls: list[RawDecl] = []
        grammar = profile.grammar or {}
        gname = grammar.get("name", profile.language)
        for suffix, alt in grammar.get("by_suffix", {}).items():
            if rel_path.endswith(suffix):
                gname = alt
        self.tree = parse(gname, source)
        self.root = self.tree.root_node
        self.imports = self._collect_imports()
        pattern = profile.calls.get("pattern")
        self.call_re = re.compile(pattern) if pattern else None
        self.known_fn_names: set[str] = set()

    # -------------------------------------------------------------- imports

    def _collect_imports(self) -> list[str]:
        if self.p.imports_hook:
            return HOOKS[self.p.imports_hook](self)
        out: list[str] = []
        rules = {r["node"]: r for r in self.p.imports}
        for n in walk(self.root):
            rule = rules.get(n.type)
            if rule is None:
                continue
            if "child_type" in rule:
                target = next((c for c in n.named_children if c.type == rule["child_type"]), None)
            else:
                target = _field_or_self(n, rule.get("field"))
            if target is not None:
                val = text(target).strip(rule.get("strip", ""))
                if val:
                    out.append(val)
        return out

    # --------------------------------------------------------------- params

    def _params(self, node) -> list[RawParam]:
        spec = self.p.params
        if "hook" in spec:
            return HOOKS[spec["hook"]](self, node)
        plist = node.child_by_field_name(spec.get("field", "parameters"))
        if plist is None:
            return []
        if plist.type == "identifier":  # single bare inferred param (Java lambda `t -> ...`)
            return [RawParam(name=text(plist))]
        out: list[RawParam] = []
        rules = spec.get("nodes", {})
        for pd in plist.named_children:
            rule = rules.get(pd.type)
            if rule is None:
                continue
            if "hook" in rule:
                out.extend(HOOKS[rule["hook"]](self, pd, len(out)))
                continue
            if rule.get("children_are_names"):  # e.g. inferred_parameters
                out.extend(RawParam(name=text(c))
                           for c in pd.named_children if c.type == "identifier")
                continue
            kind = rule.get("kind", "positional")
            if rule.get("type_from") == "first_named_child":
                tp = text(pd.named_children[0]) if pd.named_children else None
            elif rule.get("type_from_text"):
                tp = text(pd)
            else:
                tp = text(pd.child_by_field_name(rule["type_field"])) or None \
                    if "type_field" in rule else None
            names: list[str] = []
            if "name_literal" in rule:
                names = [rule["name_literal"]]
            elif "name_field" in rule:
                nm = pd.child_by_field_name(rule["name_field"])
                if nm is not None:
                    names = [text(nm)]
            elif "name_from" in rule:
                nf = rule["name_from"]
                child = next((c for c in pd.named_children if c.type == nf["child_type"]), None)
                if child is not None:
                    nm = child.child_by_field_name(nf["field"])
                    names = [text(nm)] if nm is not None else []
            elif rule.get("names_from_children"):
                names = [text(c) for c in pd.children
                         if c.type == rule["names_from_children"]]
                if names and rule.get("first_only"):
                    names = names[:1]
            if rule.get("bare_text"):
                names = [text(pd)]
            if not names:
                fallback = rule.get("fallback", "arg{i}")
                names = [fallback.format(i=len(out))]
            out.extend(RawParam(name=n, raw_type=tp, kind=kind) for n in names)
        return out

    # ------------------------------------------------- declared/writes/reads

    def _declared(self, node) -> set[str]:
        names: set[str] = set()
        for f in self.p.declare.get("param_fields", ["parameters"]):
            pl = node.child_by_field_name(f)
            if pl is not None:
                names.update(text(n) for n in walk(pl) if n.type == "identifier")
        body = _field_or_self(node, "body")
        rules = self.p.declare.get("nodes", {})
        for n in walk_own(body, self.boundaries):
            rule = rules.get(n.type)
            if rule is None:
                continue
            if "child_type" in rule:
                for c in n.named_children:
                    if c.type == rule["child_type"]:
                        nm = c.child_by_field_name(rule.get("name_field", "name"))
                        if nm is not None:
                            names.add(text(nm))
            elif rule.get("children") == "identifier":
                names.update(text(c) for c in n.children if c.type == "identifier")
            elif "name_field_direct" in rule:
                nm = n.child_by_field_name(rule["name_field_direct"])
                if nm is not None:
                    names.add(text(nm))
            elif "field" in rule:
                target = n.child_by_field_name(rule["field"])
                if target is not None:
                    ident_types = set(rule.get("ident_types", ["identifier"]))
                    names.update(text(x) for x in walk(target) if x.type in ident_types)
        return names

    def _writes(self, node) -> set[str]:
        spec = self.p.writes
        body = _field_or_self(node, "body")
        targets: set[str] = set()
        for n in walk_own(body, self.boundaries):
            if n.type in spec.get("assign", ()):
                left = n.child_by_field_name(spec.get("assign_field", "left"))
                if left is None:
                    continue
                if spec.get("assign_idents", "walk") == "walk":
                    targets.update(text(x) for x in walk(left) if x.type == "identifier")
                elif left.type == "identifier":
                    targets.add(text(left))
            elif n.type in spec.get("update", ()):
                update_field = spec.get("update_field")
                if update_field:
                    arg = n.child_by_field_name(update_field)
                    if arg is not None and arg.type == "identifier":
                        targets.add(text(arg))
                else:
                    targets.update(text(x) for x in walk(n) if x.type == "identifier")
        return targets

    def _reads(self, node) -> set[str]:
        body = _field_or_self(node, "body")
        return {text(n) for n in walk_own(body, self.boundaries) if n.type == "identifier"}

    def _closure_state(self, node, anc_declared: set[str], floor: str) -> str:
        own = self._declared(node)
        writes = {w for w in self._writes(node) if w not in own and w in anc_declared}
        if writes:
            return "mutates_captured"
        if floor != "pure":
            return floor
        reads = {r for r in self._reads(node) if r not in own and r in anc_declared}
        return "reads_captured" if reads else "pure"

    def _instance_state(self, node) -> str:
        spec = self.p.instance
        prefix = spec.get("member_prefix", "this.")
        body = _field_or_self(node, "body")
        reads = False
        for n in walk_own(body, self.boundaries):
            if n.type in spec.get("assign", ()) :
                left = n.child_by_field_name("left")
                if left is not None and text(left).startswith(prefix):
                    return "mutates_instance"
            elif n.type in spec.get("update", ()):
                if text(n).startswith(prefix):
                    return "mutates_instance"
            elif n.type == spec.get("this_node", "this"):
                reads = True
        return "reads_instance" if reads else "pure"

    # ---------------------------------------------------------------- calls

    def _calls(self, node, params: list[RawParam] | None = None,
               tables: dict | None = None) -> list[str]:
        """Raw call names in ``node``'s own body.

        With ``params`` given (indexing with ``meta``), a call through one of them
        is ``param:<name>`` and a call through a subscript is ``table:<name>``,
        with where ``<name>`` is declared recorded in ``tables`` (#39). Without
        it the output is exactly what it always was.
        """
        spec = self.p.calls
        body = _field_or_self(node, "body")
        boundaries = set(spec.get("boundaries", []))
        calls: list[str] = []
        for n in walk_own(body, boundaries):
            if params is not None:
                marker = self._indirect_call(n, node, params, tables)
                if marker is not None:
                    if marker not in calls:
                        calls.append(marker)
                    continue
            if n.type != spec.get("node"):
                continue
            if "compose" in spec:
                obj = n.child_by_field_name(spec["compose"]["object"])
                name = n.child_by_field_name(spec["compose"]["name"])
                if name is None:
                    continue
                raw = (text(obj) + "." if obj is not None else "") + text(name)
            else:
                fn = n.child_by_field_name(spec.get("field", "function"))
                if fn is None:
                    continue
                raw = text(fn)
            if spec.get("known_only") and raw not in self.known_fn_names:
                continue
            if self.call_re is not None and not self.call_re.match(raw):
                continue
            t = raw
            for old, new in spec.get("replace", {}).items():
                t = t.replace(old, new)
            # membership tested on the raw spelling, matching the legacy extractors
            if raw not in calls:
                calls.append(t)
        return calls

    # ------------------------------------------------- functions as values

    def _indirect_call(self, n, owner, params: list[RawParam], tables: dict | None) -> str | None:
        """``param:<name>`` or ``table:<name>`` when ``n`` calls through one, else None."""
        table = self.meta_specs.get("table_calls")
        if table is not None:
            for rule in table.get("calls", ()):
                if n.type != rule["node"]:
                    continue
                callee = n.child_by_field_name(rule["callee"])
                if callee is None or callee.type != rule["subscript"]:
                    continue
                obj = (callee.child_by_field_name(rule["object"]) if rule.get("object")
                       else (callee.named_children[0] if callee.named_children else None))
                # T[k]["fn"](x): the table is the innermost subscripted object (#40)
                while obj is not None and obj.type == rule["subscript"]:
                    obj = (obj.child_by_field_name(rule["object"]) if rule.get("object")
                           else (obj.named_children[0] if obj.named_children else None))
                name = _dotted_name(text(obj)) if obj is not None else None
                if name is None:
                    continue
                root = name.split(".", 1)[0]
                scope = self._table_scope(root, owner, params)
                if rule.get("require_declared") and scope == ("module", None) \
                        and root not in self._module_declared():
                    continue           # a generic type conversion, not a table
                if tables is not None:
                    tables[f"table:{name}"] = scope
                return f"table:{name}"
        pcalls = self.meta_specs.get("param_calls")
        if pcalls is not None and n.type == self.p.calls.get("node"):
            member = pcalls.get("member")
            if member is not None:
                # a language that invokes a callable through a method on it
                # (Java's f.apply(x)): the object must be a parameter typed as one
                obj = n.child_by_field_name(member["object"])
                if obj is None or obj.type != "identifier":
                    return None
                fn_types = [re.compile(t) for t in member.get("fn_types", ())]
                typed = {p.name for p in params if p.kind != "receiver" and p.raw_type
                         and any(t.search(p.raw_type) for t in fn_types)}
                return f"param:{text(obj)}" if text(obj) in typed else None
            fn = n.child_by_field_name(self.p.calls.get("field", "function"))
            if fn is None:
                return None
            raw = text(fn)
            for pattern in pcalls.get("unwrap", ()):
                m = re.match(pattern, raw)
                if m:
                    raw = m.group(1)
            if raw in {p.name for p in params if p.kind != "receiver"}:
                return f"param:{raw}"
        return None

    def _module_declared(self) -> set[str]:
        if self._module_names is None:
            self._module_names = self._declared(self.root)
        return self._module_names

    def _emitted_ancestors(self, node):
        """(decl, node) for every already-emitted item enclosing ``node``, innermost first."""
        p = node.parent
        while p is not None:
            hit = self._emitted.get(p.id)
            if hit is not None:
                yield hit
            p = p.parent

    def _table_scope(self, root: str, owner, params: list[RawParam]) -> tuple:
        """Where the table a call goes through is declared, innermost scope first."""
        spec = self.meta_specs.get("table_calls") or {}
        receivers = {p.name for p in params if p.kind == "receiver"}
        if root in receivers or root in spec.get("receiver_names", ()):
            return ("receiver", None)
        if root in {p.name for p in params} | self._declared(owner):
            return ("self", None)
        for decl, anc in self._emitted_ancestors(owner):
            if root in {p.name for p in decl.params} | self._declared(anc):
                return ("item", decl)
        return ("module", None)

    def _decorators(self, node) -> list[str]:
        spec = self.meta_specs.get("decorators")
        if spec is None:
            return []
        found = []
        siblings = set(spec.get("siblings", ()))
        if siblings:
            before = []
            p = node.prev_named_sibling
            while p is not None and (p.type in siblings or "comment" in p.type):
                if p.type in siblings:
                    before.append(p)
                p = p.prev_named_sibling
            found += reversed(before)
        children = set(spec.get("children", ()))
        within = spec.get("within", {})
        for c in node.named_children:
            if c.type in children:
                found.append(c)
            elif c.type in within:
                found += [g for g in c.named_children if g.type in within[c.type]]
        out = []
        for d in found:
            t = " ".join(text(d).split())
            for pattern in spec.get("strip", ()):
                t = re.sub(pattern, "", t)
            out.append(t.strip())
        return out

    def _returns_nested(self, node, spec: dict) -> bool:
        """Does a return statement in ``node`` hand back a function defined in it?"""
        return_nodes = set(spec.get("return_nodes", ()))
        if not return_nodes:
            return False
        body = _field_or_self(node, "body")
        nested: set[str] = set()
        returned = []
        for n in walk_own(body, self.boundaries):
            if n.type in self.p.declarations:
                nm = n.child_by_field_name("name")
                if nm is None and n.parent is not None:
                    nm = n.parent.child_by_field_name("name")
                if nm is not None:
                    nested.add(text(nm))
            elif n.type in return_nodes and n.named_children:
                returned.append(n.named_children[0])
        for expr in returned:
            while expr.type in spec.get("unwrap", ()) and expr.named_children:
                expr = expr.named_children[0]
            if expr.type in self.p.declarations:
                return True
            if expr.type == "identifier" and text(expr) in nested:
                return True
        return False

    def _apply_meta(self, decl: RawDecl, node, returns_fn: bool | None) -> None:
        if self.meta_specs.get("parent") is not None:
            decl.parent = next((d for d, _ in self._emitted_ancestors(node)), None)
        decl.decorators = self._decorators(node)
        takes = self.meta_specs.get("takes_fn")
        if takes is not None:
            fn_types = [re.compile(t) for t in takes.get("fn_types", ())]
            decl.takes_fn = any(
                p.raw_type and any(t.search(p.raw_type) for t in fn_types)
                for p in decl.params
            ) or any(c.startswith("param:") for c in decl.calls)
        rets = self.meta_specs.get("returns_fn")
        if rets is not None:
            fn_types = [re.compile(t) for t in rets.get("fn_types", ())]
            decl.returns_fn = bool(returns_fn) or bool(
                decl.returns_raw and any(t.search(decl.returns_raw) for t in fn_types)
            ) or self._returns_nested(node, rets)
        for key, scope in decl.table_scopes.items():
            if scope[0] == "self":
                decl.table_scopes[key] = ("item", decl)

    # ----------------------------------------------------------------- emit

    def _is_async(self, node) -> bool:
        if self.p.raw.get("is_async_hook"):
            return HOOKS[self.p.raw["is_async_hook"]](self, node)
        spec = self.p.raw.get("is_async")
        if not spec:
            return False
        return any(c.type == spec["child_type"] for c in node.children)

    def emit(self, node, name, kind, scope, classes, params, state,
             returns_raw=None, returns_norm=None, returns_fn=None) -> None:
        """``returns_fn`` lets a hook say a callable is returned when the return
        type's spelling cannot (C's ``int (*f(void))(int)``); only read with ``meta``."""
        doc_types = self.p.doc.get("types")
        if self.p.doc.get("hook"):
            raw_doc = HOOKS[self.p.doc["hook"]](self, node)
        else:
            raw_doc = preceding_doc(node, set(doc_types) if doc_types else None)
        tables: dict = {}
        decl = RawDecl(
            name=name,
            kind=kind,
            language=self.p.language,
            file=self.rel_path,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            scope_chain=list(scope),
            class_chain=list(classes),
            params=params,
            returns_raw=returns_raw,
            returns_norm=returns_norm,
            is_async=self._is_async(node),
            doc=_clean_doc(raw_doc, self.p.doc.get("clean")),
            body_text=text(node),
            calls=self._calls(node, params if self.meta else None, tables),
            imports=list(self.imports),
            state_capture=state,
            table_scopes=tables,
        )
        if self.meta:
            self._apply_meta(decl, node, returns_fn)
            self._emitted[node.id] = (decl, node)
        self.decls.append(decl)

    # ---------------------------------------------------------------- walks

    def run(self) -> list[RawDecl]:
        if self.p.mode == "flat":
            self._run_flat()
        else:
            init_hook = self.p.raw.get("init_declared_hook")
            seed = HOOKS[init_hook](self) if init_hook else set()
            self._visit(self.root, [], [], seed, False)
        return self.decls

    def _run_flat(self) -> None:
        decl_types = set(self.p.declarations)
        nodes = [n for n in walk(self.root) if n.type in decl_types]
        name_field = next(iter(self.p.declarations.values())).get("name", {}).get("field", "name")
        self.known_fn_names = {text(n.child_by_field_name(name_field)) for n in nodes}
        fixed = self.p.fixed_signature or {}
        params = [RawParam(**pspec) for pspec in fixed.get("params", [])]
        for node in nodes:
            self.emit(
                node, text(node.child_by_field_name(name_field)), "function",
                [], [], list(params), "pure",
                returns_norm=fixed.get("returns_norm"),
            )

    def _visit(self, node, scope, classes, anc_declared, in_func) -> None:
        for child in node.children:
            t = child.type
            container = self.p.containers.get(t)
            spec = self.p.declarations.get(t)
            if container is not None:
                cname = text(child.child_by_field_name(container.get("name_field", "name")))
                if container.get("name_strip_generics"):
                    cname = cname.split("<")[0].strip()
                if not cname:
                    cname = container.get("name_missing", cname)
                new_classes = [*classes, cname] if container.get("role") == "class" else classes
                new_scope = scope if (
                    container.get("scope_skip_duplicate") and cname in scope
                ) else [*scope, cname]
                self._visit(child, new_scope, new_classes, anc_declared, in_func)
            elif spec is not None:
                self._handle(child, spec, scope, classes, anc_declared, in_func)
            else:
                self._visit(child, scope, classes, anc_declared, in_func)

    def _handle(self, node, spec, scope, classes, anc_declared, in_func) -> None:
        if "handler" in spec:
            HOOKS[spec["handler"]](self, node, spec, scope, classes, anc_declared, in_func)
            return
        name_spec = spec.get("name")
        name = (text(node.child_by_field_name(name_spec["field"]))
                if isinstance(name_spec, dict) else name_spec)
        kind = spec.get("kind", "function")
        if kind == "auto":
            kind = "method" if classes else ("closure" if in_func else "function")
        capture = spec.get("capture", "fixed")
        if capture == "closure":
            state = self._closure_state(node, anc_declared, spec.get("floor", "pure"))
        elif capture == "instance_this":
            state = self._instance_state(node)
        else:
            state = spec.get("state", "pure")
        params = self._params(node)
        returns_raw = None
        if spec.get("returns"):
            rt = node.child_by_field_name(spec["returns"]["field"])
            returns_raw = text(rt) or None if rt is not None else None
        returns_norm = None
        if self.p.returns_norm_hook:
            returns_norm = HOOKS[self.p.returns_norm_hook](self, node)
        self.emit(node, name, kind, scope, classes, params, state, returns_raw, returns_norm)
        mode = spec.get("recurse_scope", "name" if isinstance(name_spec, dict) else "anon")
        if mode == "same":
            new_scope = scope
        elif mode == "anon":
            new_scope = [*scope, f"anon{node.start_point[0] + 1}"]
        else:
            new_scope = [*scope, name]
        self._visit(node, new_scope, classes,
                    anc_declared | self._declared(node), True)


def extract_with_profile(profile: LanguageProfile, rel_path: str, source: str,
                         meta: bool = False) -> list[RawDecl]:
    """``meta`` adds what #39 records about functions used as values; the default
    output is unchanged."""
    return ProfileWalker(profile, rel_path, source, meta).run()


# ------------------------------------------------- functions held in data (#40)

def _pick(node, where):
    """A child by field name, or by index into the named children (``-1`` = last)."""
    if where is None:
        return None
    if isinstance(where, int):
        kids = [c for c in node.named_children if "comment" not in c.type]
        return kids[where] if -len(kids) <= where < len(kids) else None
    return node.child_by_field_name(where)


def extract_fn_tables_with_profile(profile: LanguageProfile, rel_path: str,
                                   source: str) -> list[RawFnTable]:
    """Top-level dict and list literals of functions, as the profile's
    ``fn_tables`` spec spells them (#40). Members are names as written; a table
    with none that name a function is dropped by ``build_index``.

    The spec: ``declarations`` (node, and the fields holding its name and
    value), ``name_nodes`` (what a name is, found depth-first in the name field),
    ``unwrap`` (wrapper node -> field or index of what it wraps; null = first
    named child), ``containers`` (literal node -> ``entries``: entry node -> where
    its key and value are; an element that is not an entry makes a list),
    ``members`` (node types that name a function) and ``keys`` (key node type ->
    core-1 type).
    """
    spec = fn_tables_for(profile.language)
    if not spec:
        return []
    walker = ProfileWalker(profile, rel_path, source)
    enclosing = set(profile.declarations) | set(profile.boundaries)
    unwrap = spec.get("unwrap", {})
    members = set(spec.get("members", ()))
    keys = spec.get("keys", {})
    name_nodes = set(spec.get("name_nodes", ("identifier",)))

    def unwrapped(node):
        while node is not None and node.type in unwrap:
            where = unwrap[node.type]
            node = _pick(node, 0 if where is None else where)
        return node

    out: list[RawFnTable] = []
    decl_specs = {d["node"]: d for d in spec.get("declarations", ())}
    for node in walk(walker.root):
        d = decl_specs.get(node.type)
        if d is None:
            continue
        p = node.parent
        while p is not None and p.type not in enclosing:
            p = p.parent
        if p is not None:
            continue                       # inside a function: not a table of the module
        name_node = node.child_by_field_name(d["name"])
        name_node = next((n for n in walk(name_node) if n.type in name_nodes), None) \
            if name_node is not None else None
        value = unwrapped(node.child_by_field_name(d["value"]))
        if name_node is None or value is None or value.type not in spec["containers"]:
            continue
        entries = spec["containers"][value.type].get("entries", {})
        refs: list[str] = []
        key_types: set[str] = set()
        is_dict = False
        for child in value.named_children:
            if "comment" in child.type:
                continue
            child = unwrapped(child)
            if child is None:
                continue
            if child.type in entries:
                is_dict = True
                key = unwrapped(_pick(child, entries[child.type].get("key")))
                key_types.add(keys.get(key.type, "any") if key is not None else "any")
                child = unwrapped(_pick(child, entries[child.type].get("value")))
            if child is not None and child.type in members:
                refs.append(text(child))
        if is_dict:
            kind, key_type = "dict", key_types.pop() if len(key_types) == 1 else "any"
        else:
            kind, key_type = "list", "int"
        out.append(RawFnTable(
            name=text(name_node), file=rel_path,
            start_line=node.start_point[0] + 1, end_line=node.end_point[0] + 1,
            kind=kind, key_type=key_type, members=refs))
    return out


# ------------------------------------------------------- data structures (#44)

def _path(node, path):
    """Follow ``path`` -- a field name, an index into the named children, or a
    list of those -- from ``node``; None if any step is missing."""
    steps = path if isinstance(path, list) else [path]
    for step in steps:
        if node is None:
            return None
        node = _pick(node, step)
    return node


def _name_at(node, where) -> str | None:
    """The name of ``node``: itself when ``where`` is None, else what ``where`` picks."""
    target = node if where is None else _path(node, where)
    return text(target) or None if target is not None else None


class _TypeWalker:
    """Reads the type declarations a profile's ``datatypes`` spec describes."""

    def __init__(self, profile: LanguageProfile, rel_path: str, source: str, spec: dict):
        self.p, self.rel, self.spec = profile, rel_path, spec
        self.walker = ProfileWalker(profile, rel_path, source)
        self.root = self.walker.root

    def scope(self, node) -> list[str]:
        scopes = set(self.spec.get("scopes", ()))
        out: list[str] = []
        p = node.parent
        while p is not None:
            if p.type in scopes:
                name = p.child_by_field_name("name")
                if name is not None:
                    out.append(text(name))
            p = p.parent
        return out[::-1]

    def type_params(self, node, where) -> list[str]:
        holder = _path(node, where) if where is not None else None
        if holder is None:
            return []
        spec = self.spec.get("type_params", {})
        out: list[str] = []
        for child in holder.named_children:
            if child.type in spec:
                where_name = spec[child.type]
                names = child.children_by_field_name(where_name) \
                    if isinstance(where_name, str) else []
                if names:
                    out += [text(n) for n in names]
                else:
                    name = _name_at(child, where_name)
                    if name:
                        out.append(name)
        return out

    def fields(self, container) -> list[tuple[str, str | None]] | None:
        """Fields of a field-list node, or None when it is not a field list the
        spec knows (a shape the index would otherwise show as empty)."""
        if container is None:
            return []
        spec = self.spec.get("fields", {}).get(container.type)
        if spec is None:
            return None
        if "positional" in spec:
            return [(str(i), text(t)) for i, t in
                    enumerate(container.children_by_field_name(spec["positional"]))]
        out: list[tuple[str, str | None]] = []
        for child in container.named_children:
            if child.type not in spec["node"]:
                continue
            type_node = _path(child, spec["type"])
            raw = text(type_node) if type_node is not None else None
            mark = spec.get("optional_mark")
            if raw is not None and mark and any(c.type == mark for c in child.children):
                raw = spec["optional_spelling"].format(raw)
            names = [text(n) for n in child.children_by_field_name(spec["name"])]
            if not names and spec.get("embedded") and raw:
                names = [re.split(r"[.\s*\[]", raw.lstrip("*"))[-1] or raw]
            out += [(n, raw) for n in names]
        return out

    def _base(self, node, d: dict, kind: str, **kw) -> RawType:
        return RawType(name=_name_at(node, d.get("name", "name")) or "", kind=kind,
                       file=self.rel, start_line=node.start_point[0] + 1,
                       end_line=node.end_point[0] + 1, language=self.p.language,
                       type_params=self.type_params(node, d.get("type_params")),
                       scope_chain=self.scope(node), **kw)

    @staticmethod
    def _required(node, d: dict) -> bool:
        for where, node_type in d.get("require", {}).items():
            got = node.child_by_field_name(where)
            if got is None or (node_type is not None and got.type != node_type):
                return False
        return True

    def record(self, node, d: dict) -> RawType | None:
        fields = self.fields(_path(node, d["fields"]))
        return None if fields is None else self._base(node, d, "record", fields=fields)

    def enum(self, node, d: dict) -> RawType | None:
        body = _path(node, d["body"])
        variants: list = []
        for child in (body.named_children if body is not None else []):
            v = d["variants"].get(child.type)
            if v is None:
                continue
            fields = self.fields(_path(child, v["fields"])) if v.get("fields") else []
            if fields is None:
                return None
            variants.append((_name_at(child, v.get("name")), fields))
        return self._base(node, d, "variant", variants=variants)

    def union(self, node, d: dict) -> RawType | None:
        """A sum spelled as a list of types: names of other types (``refs``),
        inline object types tagged by a literal-typed field (``inline``), or bare
        literals (``tags``). Anything else in the list makes it not a sum."""
        top = _path(node, d["members"])
        flatten = set(d.get("flatten", ()))
        leaves: list = []

        def gather(n):
            if n.type in flatten:
                for c in n.named_children:
                    gather(c)
            else:
                leaves.append(n)
        if top is None:
            return None
        if d.get("descend"):
            leaves = [n for n in walk(top) if n.type in d.get("refs", ())]
        else:
            gather(top)
        variants: list = []
        for leaf in leaves:
            if leaf.type in d.get("refs", ()):
                variants.append((text(leaf), None))
            elif leaf.type in d.get("tags", ()) and _quoted(text(leaf)):
                variants.append((_quoted(text(leaf)), []))
            elif leaf.type in d.get("inline", ()):
                fields = self.fields(leaf)
                tag = [f for f in fields or [] if _quoted(f[1] or "")]
                if fields is None or len(tag) != 1:
                    return None
                variants.append((_quoted(tag[0][1]), [f for f in fields if f is not tag[0]]))
            else:
                return None
        if len(variants) < 2:
            return None
        return self._base(node, d, "variant", variants=variants)

    def run(self) -> list[RawType]:
        rules = [(d, self.record) for d in self.spec.get("records", ())] \
            + [(d, self.enum) for d in self.spec.get("enums", ())] \
            + [(d, self.union) for d in self.spec.get("unions", ())]
        by_node: dict[str, list] = {}
        for d, fn in rules:
            by_node.setdefault(d["node"], []).append((d, fn))
        out: list[RawType] = []
        for node in walk(self.root):
            for d, fn in by_node.get(node.type, ()):
                if not self._required(node, d):
                    continue
                t = fn(node, d)
                if t is not None and t.name:
                    out.append(t)
                    break
        for name in self.spec.get("hooks", ()):
            out += HOOKS[name](self)
        out.sort(key=lambda t: (t.start_line, t.name))
        return out


def _quoted(s: str) -> str | None:
    """The contents of a quoted string literal, else None."""
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'`":
        return s[1:-1]
    return None


def extract_types_with_profile(profile: LanguageProfile, rel_path: str,
                               source: str) -> list[RawType]:
    """The data-structure declarations in one file, as the profile's ``datatypes``
    spec spells them (#44); ``[]`` when the language declares none.

    The spec: ``records`` / ``enums`` / ``unions`` (each a list of rules: the
    declaration ``node``, where its ``name`` and ``type_params`` are, a
    ``require`` guard of field -> node type, and where its members are),
    ``fields`` (field-list node -> which children are fields and where their
    name and type are, or ``positional``), ``type_params`` (parameter node ->
    where its name is), ``scopes`` (nodes whose name prefixes a nested
    declaration's) and ``hooks`` for idioms no node pattern captures.
    """
    spec = datatypes_for(profile.language)
    if not spec:
        return []
    return _TypeWalker(profile, rel_path, source, spec).run()


# ------------------------------------------------------------- hook library

@hook("go_multi_return")
def _go_multi_return(walker: ProfileWalker, node) -> str:
    from spindlebox.typenorm import go_return
    result = node.child_by_field_name("result")
    if result is None:
        types = []
    elif result.type == "parameter_list":
        types = []
        for pd in result.named_children:
            tp = pd.child_by_field_name("type")
            types.append(text(tp) if tp is not None else text(pd))
    else:
        types = [text(result)]
    return go_return(types)


@hook("go_method")
def _go_method(walker: ProfileWalker, node, spec, scope, classes, anc_declared, in_func):
    """Go method_declaration: explicit receiver param, receiver-based state."""
    name = text(node.child_by_field_name("name"))
    params = walker._params(node)
    recv = node.child_by_field_name("receiver")
    recv_name, recv_type = "", ""
    if recv is not None and recv.named_children:
        pd = recv.named_children[0]
        idents = [text(c) for c in pd.children if c.type == "identifier"]
        recv_name = idents[0] if idents else ""
        recv_type = text(pd.child_by_field_name("type")).lstrip("*")
        params.insert(0, RawParam(name=recv_name or "recv", raw_type=recv_type, kind="receiver"))

    state = "pure"
    if recv_name:
        body = node.child_by_field_name("body")
        writes = walker._writes(node)
        reads = False
        if body is not None:
            for n in walk_own(body, {"func_literal"}):
                if n.type == "selector_expression":
                    operand = n.child_by_field_name("operand")
                    if operand is not None and text(operand) == recv_name:
                        reads = True
        if recv_name in writes:
            state = "mutates_instance"
        else:
            done = False
            if body is not None:
                for n in walk_own(body, {"func_literal"}):
                    if n.type == "assignment_statement":
                        left = n.child_by_field_name("left")
                        if left is not None and any(
                            x.type == "selector_expression"
                            and text(x.child_by_field_name("operand") or x) == recv_name
                            for x in walk(left)
                        ):
                            state = "mutates_instance"
                            done = True
                            break
            if not done and state == "pure":
                state = "reads_instance" if reads else "pure"

    rt = node.child_by_field_name("result")
    returns_norm = HOOKS[walker.p.returns_norm_hook](walker, node) \
        if walker.p.returns_norm_hook else None
    walker.emit(node, name, "method",
                [recv_type] if recv_type else [], [recv_type] if recv_type else [],
                params, state, text(rt) or None if rt is not None else None, returns_norm)
    walker._visit(node, [*scope, name], classes,
                  anc_declared | walker._declared(node), True)


@hook("bash_source_imports")
def _bash_source_imports(walker: ProfileWalker) -> list[str]:
    imports = []
    for n in walk(walker.root):
        if n.type == "command":
            name_node = n.child_by_field_name("name")
            if name_node is not None and text(name_node) in ("source", "."):
                args = [c for c in n.children if c.type in ("word", "string", "raw_string")]
                if args:
                    imports.append(text(args[-1]).strip("'\""))
    return imports


# ---- rust hooks (mirror rust_lang.py: self receiver, move closures, async) ----

def _rust_self_state(walker: ProfileWalker, node, self_kind: str) -> str:
    body = node.child_by_field_name("body")
    if body is not None:
        for n in walk_own(body, walker.boundaries):
            if n.type in ("assignment_expression", "compound_assignment_expr"):
                left = n.child_by_field_name("left")
                if left is not None and text(left).startswith("self."):
                    return "mutates_instance"
    if "&mut" in self_kind:
        return "mutates_instance"
    if self_kind.strip() == "self":
        return "consumes"
    return "reads_instance"


@hook("rust_is_async")
def _rust_is_async(walker: ProfileWalker, node) -> bool:
    return any(c.type == "async" or text(c) == "async" for c in node.children
               if not c.is_named or c.type == "function_modifiers")


@hook("rust_function_item")
def _rust_function_item(walker, node, spec, scope, classes, anc_declared, in_func):
    name = text(node.child_by_field_name("name"))
    params = walker._params(node)
    self_kind = next((q.raw_type for q in params if q.kind == "receiver"), None)
    rt = node.child_by_field_name("return_type")
    if self_kind is not None:
        kind, state = "method", _rust_self_state(walker, node, self_kind)
    elif in_func:
        kind, state = "closure", "pure"
    else:
        kind, state = ("method", "pure") if classes else ("function", "pure")
    walker.emit(node, name, kind, scope, classes, params, state,
                returns_raw=text(rt) if rt is not None else None)
    walker._visit(node, [*scope, name], classes,
                  anc_declared | walker._declared(node), True)


@hook("rust_closure")
def _rust_closure(walker, node, spec, scope, classes, anc_declared, in_func):
    own = walker._declared(node)
    writes = {w for w in walker._writes(node) if w not in own and w in anc_declared}
    reads = {r for r in walker._reads(node) if r not in own and r in anc_declared}
    moved = any(text(c) == "move" for c in node.children if not c.is_named)
    if writes:
        state = "mutates_captured"
    elif moved:
        state = "consumes"
    elif reads:
        state = "reads_captured"
    else:
        state = "pure"
    walker.emit(node, "<closure>", "closure", scope, classes,
                walker._params(node), state, returns_raw=None)
    walker._visit(node, scope, classes, anc_declared | own, True)


# ---- js/ts hooks (mirror js_lang.py: name inference, destructuring, doc hops) ----

_JS_FUNC_TYPES = {
    "function_declaration", "generator_function_declaration", "function_expression",
    "generator_function", "arrow_function", "method_definition",
}
_JS_CLASS_TYPES = {"class_declaration", "class"}
_JS_CALL_RE = re.compile(r"^[A-Za-z_$][\w$]*(\.[\w$]+)*$")


@hook("js_imports")
def _js_imports(walker: ProfileWalker) -> list[str]:
    imports = []
    for n in walk(walker.root):
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


@hook("js_module_declared")
def _js_module_declared(walker: ProfileWalker) -> set[str]:
    return {
        text(n.child_by_field_name("name") or n)
        for n in walk_own(walker.root, _JS_FUNC_TYPES | _JS_CLASS_TYPES)
        if n.type == "variable_declarator"
    }


@hook("js_params")
def _js_params(walker: ProfileWalker, func_node) -> list[RawParam]:
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


@hook("js_doc")
def _js_doc(walker: ProfileWalker, node) -> str | None:
    doc = preceding_doc(node)
    if doc:
        return doc
    p = node.parent
    hops = 0
    while p is not None and hops < 4:
        if p.type in ("lexical_declaration", "variable_declaration", "export_statement",
                      "expression_statement"):
            return preceding_doc(p)
        p = p.parent
        hops += 1
    return None


def _js_name_for(node) -> str | None:
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
            if _JS_CALL_RE.match(left):
                return left.rsplit(".", 1)[-1]
    return None


def _js_this_capture(walker: ProfileWalker, node) -> str:
    body = node.child_by_field_name("body") or node
    reads = False
    for n in walk_own(body, _JS_FUNC_TYPES):
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


@hook("js_function")
def _js_function(walker, node, spec, scope, classes, anc_declared, in_func):
    name = _js_name_for(node)
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
        state = _js_this_capture(walker, node)
    else:
        own = walker._declared(node)
        writes = {w for w in walker._writes(node) if w not in own and w in anc_declared}
        reads = {r for r in walker._reads(node) if r not in own and r in anc_declared}
        if writes:
            state = "mutates_captured"
        elif reads and (in_func or kind in ("closure", "lambda")):
            state = "reads_captured"
        else:
            state = "pure"

    rt = node.child_by_field_name("return_type")
    walker.emit(node, name, kind, scope, classes, walker._params(node), state,
                returns_raw=text(rt).lstrip(":").strip() if rt is not None else None)
    walker._visit(node,
                  [*scope, name if not anonymous else f"anon{node.start_point[0] + 1}"],
                  classes, anc_declared | walker._declared(node), True)


# ---- c hooks (the name sits under a declarator chain, not in a direct field) ----

# every node type that can appear as a link in a C declarator chain, i.e.
# `char **split_words(...)` -> pointer_declarator -> pointer_declarator ->
# function_declarator -> identifier.
_C_DECLARATOR_CHAIN = {
    "init_declarator", "pointer_declarator", "abstract_pointer_declarator",
    "array_declarator", "abstract_array_declarator",
    "function_declarator", "abstract_function_declarator",
    "parenthesized_declarator", "attributed_declarator",
}

# how to get from a write target back to the variable it lands on
_C_WRITE_BASE_FIELDS = {
    "subscript_expression": "argument",   # g[i]
    "field_expression": "argument",       # g.f and g->f
    "pointer_expression": "argument",     # *g
    "cast_expression": "value",           # ((T)g)
}


def _c_inner_declarator(node):
    """Next link down a C declarator chain: the declarator field, else the nested one.

    `parenthesized_declarator` carries no field, so fall back to its one named child.
    Using the field where it exists is what keeps an initializer (`= fopen(...)`)
    out of the walk.
    """
    nxt = node.child_by_field_name("declarator")
    if nxt is not None:
        return nxt
    for c in node.named_children:
        if c.type == "identifier" or c.type in _C_DECLARATOR_CHAIN:
            return c
    return None


def _c_declarator_identifier(node):
    """Descend a declarator chain to the identifier it finally names, or None."""
    cur = node
    for _ in range(32):
        if cur is None or cur.type == "identifier":
            return cur
        cur = _c_inner_declarator(cur)
    return None


def _c_base_identifier(node):
    """The variable a write lands on: `g`, `g[i]`, `g->f`, `*g`, `(*g).f` -> `g`."""
    cur = node
    for _ in range(32):
        if cur is None:
            return None
        if cur.type == "identifier":
            return text(cur)
        field = _C_WRITE_BASE_FIELDS.get(cur.type)
        if field is not None:
            cur = cur.child_by_field_name(field)
        elif cur.type == "parenthesized_expression":
            cur = cur.named_children[0] if cur.named_children else None
        else:
            return None
    return None


def _c_local_names(walker: ProfileWalker, node) -> set[str]:
    """Names declared in this body — the declarator only, never the initializer.

    Walking the whole `declaration` would also collect the names *read* by an
    initializer (`int n = g_count;`), and every one of those would then look
    local, hiding the file-scope state this function actually touches.
    """
    body = node.child_by_field_name("body")
    if body is None:
        return set()
    names: set[str] = set()
    for n in walk_own(body, walker.boundaries):
        if n.type != "declaration":
            continue
        for child in n.named_children:
            if child.type == "identifier" or child.type in _C_DECLARATOR_CHAIN:
                ident = _c_declarator_identifier(child)
                if ident is not None:
                    names.add(text(ident))
    return names


def _c_state(walker: ProfileWalker, node, params: list[RawParam]) -> str:
    """C's analogue of capture: does the body reach outside its own frame?

    C has no closures, so `captured` means file scope — a global, a static, an
    enum constant or an object-like macro. A function that only touches its own
    locals, parameters and callees is `pure` in the SPI sense.
    """
    body = node.child_by_field_name("body")
    if body is None:
        return "pure"
    local = _c_local_names(walker, node) | {p.name for p in params}
    callees: set[str] = set()
    mutated: list[str] = []
    read: list[str] = []
    for n in walk_own(body, walker.boundaries):
        if n.type == "call_expression":
            fn = n.child_by_field_name("function")
            if fn is not None and fn.type == "identifier":
                callees.add(text(fn))
        elif n.type == "assignment_expression":
            base = _c_base_identifier(n.child_by_field_name("left"))
            if base:
                mutated.append(base)
        elif n.type == "update_expression":
            base = _c_base_identifier(n.child_by_field_name("argument"))
            if base:
                mutated.append(base)
        elif n.type == "identifier":
            read.append(text(n))
    outside = local | callees
    if any(m not in outside for m in mutated):
        return "mutates_captured"
    if any(r not in outside for r in read):
        return "reads_captured"
    return "pure"


# `T * __cdecl name(...)` is ambiguous to tree-sitter-c whenever T is not one of
# the grammar's primitive-type keywords: `undefined4 * __cdecl f(x)` parses as a
# multiplication, the whole definition collapses into an ERROR node, and the
# function vanishes from the index. Ghidra spells nearly every function that way,
# so this is not an edge case on decompiled input. The same line without the
# calling convention parses correctly, so the convention is blanked in exactly
# that position — it is recorded in the decompiler's own metadata anyway.
_C_MS_CALL_MODIFIER = re.compile(
    r"(\*\s*)(__cdecl|__stdcall|__fastcall|__thiscall|__vectorcall|__clrcall)\b"
)


@hook("c_ms_call_modifier")
def _c_ms_call_modifier(source: str) -> str:
    """Blank a calling convention that follows a `*`, preserving every offset."""
    return _C_MS_CALL_MODIFIER.sub(lambda m: m.group(1) + " " * len(m.group(2)), source)


# `LAB_004b65de:` immediately before a `}` is a label with no statement after it,
# which is not valid C before C23 and which tree-sitter-c rejects outright — the
# whole enclosing definition becomes an ERROR node. Ghidra emits it whenever a
# jump target lands on the end of a block. Swapping the colon for a semicolon
# turns the label into a bare expression statement: same length, parses, and the
# label itself is dead anyway once the body is being read rather than executed.
# `default:` is excluded because turning it into a statement would break the
# switch it belongs to.
_C_DANGLING_LABEL = re.compile(
    r"^([ \t]*(?!default\b)[A-Za-z_]\w*):(?=[ \t]*\n[ \t]*\})", re.M
)


@hook("c_dangling_label")
def _c_dangling_label(source: str) -> str:
    """Make a label that ends a block into a statement, preserving every offset."""
    return _C_DANGLING_LABEL.sub(r"\1;", source)


@hook("c_decompiler_fixups")
def _c_decompiler_fixups(source: str) -> str:
    """Every length-preserving repair decompiled C needs before it will parse."""
    return _c_dangling_label(_c_ms_call_modifier(source))


@hook("c_param")
def _c_param(walker: ProfileWalker, node, index: int) -> list[RawParam]:
    """One C parameter: type from the `type` field, name from the declarator chain.

    Pointer and array depth is spelled back onto the type (`char` + `*`), because
    in C the declarator carries it and the type field does not. An array parameter
    decays to a pointer, which is what the language does to it anyway.
    """
    base = text(node.child_by_field_name("type"))
    decl = node.child_by_field_name("declarator")
    if decl is None:
        if base == "void":
            return []                       # `f(void)` is C for "no parameters"
        return [RawParam(name=f"arg{index}", raw_type=base or None)]
    stars = 0
    fn_params: str | None = None
    cur = decl
    for _ in range(32):
        if cur is None or cur.type == "identifier":
            break
        if cur.type in ("pointer_declarator", "abstract_pointer_declarator",
                        "array_declarator", "abstract_array_declarator"):
            stars += 1
        elif cur.type in ("function_declarator", "abstract_function_declarator"):
            plist = cur.child_by_field_name("parameters")
            fn_params = text(plist) if plist is not None else "()"
        cur = _c_inner_declarator(cur)
    name = text(cur) if cur is not None and cur.type == "identifier" else f"arg{index}"
    if fn_params is not None:                # `int (*fn)(int)` — a function pointer
        raw = f"{base} (*){fn_params}".strip()
    elif stars:
        raw = f"{base} {'*' * stars}".strip()
    else:
        raw = base
    return [RawParam(name=name, raw_type=raw or None)]


@hook("c_function")
def _c_function(walker: ProfileWalker, node, spec, scope, classes, anc_declared, in_func):
    """A C function definition: `type (pointer_declarator*) function_declarator body`.

    The name is two or more levels down the declarator chain and the parameter
    list hangs off the `function_declarator`, not off the `function_definition`,
    so neither can be reached by the walker's direct field lookup.
    """
    decl = node.child_by_field_name("declarator")
    ident = _c_declarator_identifier(decl) if decl is not None else None
    if ident is None:
        return
    fdecl = ident.parent
    while fdecl is not None and fdecl is not node and fdecl.type != "function_declarator":
        fdecl = fdecl.parent
    if fdecl is None or fdecl.type != "function_declarator":
        return
    params = walker._params(fdecl)
    stars = 0
    returns_fn = False
    cur = fdecl.parent
    while cur is not None and cur is not node:
        if cur.type in ("pointer_declarator", "array_declarator"):
            stars += 1
        elif cur.type == "function_declarator":
            returns_fn = True       # `int (*name(...))(int)` returns a function pointer
        cur = cur.parent
    base = text(node.child_by_field_name("type"))
    returns_raw = (f"{base} {'*' * stars}".strip() if stars else base) or None
    name = text(ident)
    walker.emit(node, name, "function", scope, classes, params,
                _c_state(walker, node, params), returns_raw=returns_raw,
                returns_fn=returns_fn)
    walker._visit(node, [*scope, name], classes,
                  anc_declared | walker._declared(node), True)


@hook("go_const_enums")
def _go_const_enums(tw: _TypeWalker) -> list[RawType]:
    """``type Status int`` plus a ``const`` block of ``Pending Status = iota``,
    ``Paid``, ``Shipped``: Go's enum. A const spec with no type and no value
    repeats the previous one's, so it continues the enum."""
    named: dict[str, object] = {}
    for node in walk(tw.root):
        if node.type == "type_spec":
            t = node.child_by_field_name("type")
            if t is not None and t.type == "type_identifier":
                named[text(node.child_by_field_name("name"))] = node
    members: dict[str, list[str]] = {}
    for node in walk(tw.root):
        if node.type != "const_declaration":
            continue
        current = None
        for spec in node.named_children:
            if spec.type != "const_spec":
                continue
            t = spec.child_by_field_name("type")
            if t is not None:
                current = text(t)
            elif spec.child_by_field_name("value") is not None:
                current = None
            if current in named:
                members.setdefault(current, []).extend(
                    text(n) for n in spec.children_by_field_name("name"))
    out = []
    for name, ms in members.items():
        node = named[name]
        out.append(RawType(name=name, kind="variant", file=tw.rel,
                           start_line=node.start_point[0] + 1, end_line=node.end_point[0] + 1,
                           language=tw.p.language, scope_chain=tw.scope(node),
                           variants=[(m, []) for m in ms]))
    return out


@hook("go_sealed_interfaces")
def _go_sealed_interfaces(tw: _TypeWalker) -> list[RawType]:
    """An interface whose only methods are unexported markers taking and
    returning nothing (``interface{ isPayment() }``) is a closed sum: no type
    outside the package can implement it. Its variants are the types in this
    file with a method of that name, in the order they are declared."""
    order: dict[str, int] = {}
    markers: dict[str, set[str]] = {}
    ifaces = []
    for node in walk(tw.root):
        if node.type == "type_spec":
            name = text(node.child_by_field_name("name"))
            order.setdefault(name, len(order))
            t = node.child_by_field_name("type")
            if t is None or t.type != "interface_type":
                continue
            elems = [c for c in t.named_children if "comment" not in c.type]
            if elems and all(
                    e.type == "method_elem" and text(e.child_by_field_name("name"))[:1].islower()
                    and not text(e.child_by_field_name("parameters")).strip("() \t")
                    and e.child_by_field_name("result") is None for e in elems):
                ifaces.append((node, {text(e.child_by_field_name("name")) for e in elems}))
        elif node.type == "method_declaration":
            recv = node.child_by_field_name("receiver")
            types = [text(n) for n in walk(recv) if n.type == "type_identifier"] if recv else []
            if types:
                markers.setdefault(text(node.child_by_field_name("name")), set()).add(types[0])
    out = []
    for node, methods in ifaces:
        impl = set.intersection(*(markers.get(m, set()) for m in methods))
        if not impl:
            continue
        ranked = sorted(impl, key=lambda n: (order.get(n, len(order)), n))
        out.append(RawType(name=text(node.child_by_field_name("name")), kind="variant",
                           file=tw.rel, start_line=node.start_point[0] + 1,
                           end_line=node.end_point[0] + 1, language=tw.p.language,
                           type_params=tw.type_params(node, "type_parameters"),
                           scope_chain=tw.scope(node), variants=[(n, None) for n in ranked]))
    return out
