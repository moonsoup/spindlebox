"""Data-structure declarations for generated code (#45).

The index's ``types`` section (#44) holds every record and variant in core-1 terms.
Before this module, generation ignored it: a signature ``total(Order) -> Money``
rendered both types through the type table's fallback (``serde_json::Value`` /
``Object``) because ``obj:<Name>`` was a name nothing declared. The fix is shared by
every emitter rather than patched per call site:

- ``TypeRefs`` resolves ``obj:<Name>[<args>]`` (and, inside a declaration,
  ``typevar:<T>``) against the declared types. Renderers take it as an optional
  argument; without it (or for a name no type declares) they behave exactly as before.
- ``emit_types`` writes the declarations from a ``datatypes`` block in the emit
  profile, so the legacy Rust backend and the profile engine read the same data and
  stay byte-identical by construction.

A declaration is written so the same indexer reads it back to the same canonical
shape — that round trip is the falsifiable check (gx/datastructs). Bodies stay stubs.

``sum_style`` is the one language-shaped choice: ``inline`` (Rust: an enum whose
variants carry their fields) or ``sealed`` (Java: an enum when every variant is a
bare tag, otherwise a sealed interface permitting one record per variant; a record
already declared with the same fields is reused rather than duplicated).
"""

from __future__ import annotations

from collections.abc import Callable
from string import Template

from spindlebox.schema import TypeDecl
from spindlebox.typenorm import _split_top


def _sub(tpl: str, **vars) -> str:
    return Template(tpl).substitute(vars)


class TypeRefs:
    """Resolve core-1 references to declared types for one rendering context.

    ``decl`` selects the spelling inside a declaration (``decl_ref``) versus at a use
    site (``ref``, e.g. Rust's ``crate::`` path from inside a generated module).
    ``typevars`` are the type parameters in scope; outside a declaration there are
    none and a ``typevar:`` falls through to the caller's fallback, as before.
    """

    def __init__(self, names: dict[str, str], arity: dict[str, int], spec: dict,
                 decl: bool = False, typevars: frozenset[str] = frozenset()):
        self.names = names
        self.arity = arity
        self.spec = spec
        self.decl = decl
        self.typevars = typevars

    def scoped(self, params: list[str]) -> TypeRefs:
        return TypeRefs(self.names, self.arity, self.spec, True, frozenset(params))

    def resolve(self, t: str, render: Callable[[str], str]) -> str | None:
        """Rendered reference, or None to let the caller's type table decide."""
        if t.startswith("typevar:"):
            v = t[len("typevar:"):]
            return v if v in self.typevars else None
        if not t.startswith("obj:"):
            return None
        body = t[len("obj:"):]
        args: list[str] = []
        if body.endswith(">") and "<" in body:
            body, args_s = body.split("<", 1)
            args = _split_top(args_s[:-1], ",")
        name = self.names.get(body)
        if name is None:
            return None
        n = self.arity[body]
        if len(args) != n:
            # a signature drops generic arguments (normalize, not normalize_decl);
            # the target still needs them, so each is the target's `any`
            args = ["any"] * n
        s = _sub(self.spec["decl_ref" if self.decl else "ref"], name=name)
        if n:
            s += "<" + ", ".join(render(a) for a in args) + ">"
        return s


def _fields_sig(fields: list[dict]) -> list[tuple[str, str]]:
    return [(f["name"], f["type"]) for f in fields]


def _positional(fields: list[dict]) -> bool:
    return bool(fields) and all(f["name"].isdigit() for f in fields)


def plan(types: list[TypeDecl], spec: dict, ident: Callable[[str], str],
         reserved: set[str]) -> tuple[dict[str, str], dict[str, int]]:
    """Emitted name per declared type (first declaration of a name wins), avoiding
    the generator's own names. Pure, so every emission site agrees."""
    used = set(reserved) | set(spec.get("reserved", []))
    names: dict[str, str] = {}
    arity: dict[str, int] = {}
    for t in types:
        if t.name in names:
            continue
        base = ident(t.name)
        name, k = base, 1
        while name in used:
            name = f"{base}_t" if k == 1 else f"{base}_t{k}"
            k += 1
        used.add(name)
        names[t.name] = name
        arity[t.name] = len(t.type_params)
    return names, arity


def emit_types(types: list[TypeDecl], spec: dict, ident: Callable[[str], str],
               render: Callable[[str, TypeRefs], str],
               names: dict[str, str], arity: dict[str, int]) -> list[str]:
    """Declaration lines (one type per line) for every type ``plan`` named."""
    if not names:
        return []
    refs = TypeRefs(names, arity, spec)
    indent = spec.get("indent", "")
    by_name = {t.name: t for t in reversed(types)}  # first declaration wins
    decls = [by_name[n] for n in names]

    def tparams(params: list[str]) -> str:
        return _sub(spec["type_params"], params=", ".join(params)) if params else ""

    def field_list(fields: list[dict], scope: TypeRefs, key: str) -> str:
        if _positional(fields) and f"tuple_{key}" in spec:
            return spec[f"tuple_{key}_sep"].join(
                _sub(spec[f"tuple_{key}"], type=render(f["type"], scope)) for f in fields)
        return spec[f"{key}_sep"].join(
            _sub(spec[key], field=ident(f["name"]), type=render(f["type"], scope))
            for f in fields)

    def record(name: str, params: list[str], fields: list[dict],
               implements: list[str]) -> str:
        scope = refs.scoped(params)
        tpl = spec["tuple_record"] if _positional(fields) and "tuple_record" in spec \
            else spec["record"]
        impl = _sub(spec["implements"], ifaces=spec["implements_sep"].join(implements)) \
            if implements else ""
        return _sub(tpl, indent=indent, name=name, tparams=tparams(params),
                    fields=field_list(fields, scope, "field"), implements=impl)

    out: list[str] = list(spec.get("header", []))
    if spec["sum_style"] == "inline":
        for t in decls:
            name = names[t.name]
            if t.kind == "record":
                out.append(record(name, t.type_params, t.fields, []))
                continue
            scope = refs.scoped(t.type_params)
            vs = []
            for v in t.variants:
                vname = ident(v["name"])
                if not v["fields"]:
                    vs.append(_sub(spec["variant_unit"], name=vname))
                elif _positional(v["fields"]):
                    vs.append(_sub(spec["variant_tuple"], name=vname,
                                   fields=field_list(v["fields"], scope, "variant_field")))
                else:
                    vs.append(_sub(spec["variant_struct"], name=vname,
                                   fields=field_list(v["fields"], scope, "variant_field")))
            line = _sub(spec["sum"], indent=indent, name=name, tparams=tparams(t.type_params),
                        variants=spec["variant_sep"].join(vs))
            if t.variants and "sum_default" in spec:
                first = t.variants[0]
                fname = ident(first["name"])
                if not first["fields"]:
                    dflt = fname
                elif _positional(first["fields"]):
                    dflt = _sub(spec["default_tuple"], name=fname, fields=", ".join(
                        spec["default_value"] for _ in first["fields"]))
                else:
                    dflt = _sub(spec["default_struct"], name=fname, fields=", ".join(
                        _sub(spec["default_field"], field=ident(f["name"]))
                        for f in first["fields"]))
                bounded = _sub(spec["type_params"], params=", ".join(
                    _sub(spec["bounded_param"], param=p) for p in t.type_params)) \
                    if t.type_params else ""
                line += _sub(spec["sum_default"], name=name, tparams=tparams(t.type_params),
                             bounded=bounded, first=dflt)
            out.append(line)
        out.append("")
        return out

    # sealed: records first learn which sums they belong to, so a record that is
    # also a variant is declared once, implementing every sum that lists it
    used = set(names.values()) | set(spec.get("reserved", []))
    implements: dict[str, list[str]] = {}
    members: dict[str, list[tuple[str, dict]]] = {}  # sum -> [(record name, variant)]
    for t in decls:
        if t.kind != "variant" or not t.variants:
            continue
        if not t.type_params and all(not v["fields"] for v in t.variants) \
                and "enum" in spec:
            continue
        sname = names[t.name]
        iface = sname + tparams(t.type_params)
        ms: list[tuple[str, dict]] = []
        for v in t.variants:
            other = by_name.get(v["name"])
            if (other is not None and other.kind == "record" and not other.type_params
                    and not t.type_params
                    and _fields_sig(other.fields) == _fields_sig(v["fields"])):
                rname = names[other.name]
                implements.setdefault(rname, []).append(iface)
                ms.append((rname, {}))
                continue
            base = ident(v["name"])
            rname, k = base, 1
            while rname in used:
                rname = f"{sname}{base}" if k == 1 else f"{sname}{base}{k}"
                k += 1
            used.add(rname)
            ms.append((rname, v))
        members[t.name] = ms
    for t in decls:
        name = names[t.name]
        if t.kind == "record":
            out.append(record(name, t.type_params, t.fields, implements.get(name, [])))
        elif t.name not in members:
            if t.variants or "sum_empty" not in spec:
                out.append(_sub(spec["enum"], indent=indent, name=name, variants=spec[
                    "enum_sep"].join(_sub(spec["enum_constant"], name=ident(v["name"]))
                                     for v in t.variants)))
            else:
                out.append(_sub(spec["sum_empty"], indent=indent, name=name,
                                tparams=tparams(t.type_params)))
        else:
            ms = members[t.name]
            out.append(_sub(spec["sum"], indent=indent, name=name,
                            tparams=tparams(t.type_params),
                            members=", ".join(r for r, _ in ms)))
            iface = name + tparams(t.type_params)
            for rname, v in ms:
                if v:
                    out.append(record(rname, t.type_params, v["fields"], [iface]))
    out.append("")
    return out
