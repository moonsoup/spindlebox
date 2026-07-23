"""Generic profile-driven extractor: one tree-sitter walk for any language.

The walk is parameterized entirely by a ``LanguageProfile`` (JSON data).
The few behaviors that resist declarative description live in the HOOKS
library below and are referenced from profiles *by name* — adding a new
language should not normally require adding a hook.
"""

from __future__ import annotations

import re

from spindlebox.extract.base import RawDecl, RawParam
from spindlebox.extract.profile_registry import LanguageProfile
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


class ProfileWalker:
    def __init__(self, profile: LanguageProfile, rel_path: str, source: str):
        self.p = profile
        self.rel_path = rel_path
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

    def _calls(self, node) -> list[str]:
        spec = self.p.calls
        body = _field_or_self(node, "body")
        boundaries = set(spec.get("boundaries", []))
        calls: list[str] = []
        for n in walk_own(body, boundaries):
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

    # ----------------------------------------------------------------- emit

    def _is_async(self, node) -> bool:
        if self.p.raw.get("is_async_hook"):
            return HOOKS[self.p.raw["is_async_hook"]](self, node)
        spec = self.p.raw.get("is_async")
        if not spec:
            return False
        return any(c.type == spec["child_type"] for c in node.children)

    def emit(self, node, name, kind, scope, classes, params, state,
             returns_raw=None, returns_norm=None) -> None:
        doc_types = self.p.doc.get("types")
        if self.p.doc.get("hook"):
            raw_doc = HOOKS[self.p.doc["hook"]](self, node)
        else:
            raw_doc = preceding_doc(node, set(doc_types) if doc_types else None)
        self.decls.append(RawDecl(
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
            calls=self._calls(node),
            imports=list(self.imports),
            state_capture=state,
        ))

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


def extract_with_profile(profile: LanguageProfile, rel_path: str, source: str) -> list[RawDecl]:
    return ProfileWalker(profile, rel_path, source).run()


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
