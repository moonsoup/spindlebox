"""Rust skeleton backend: SCA index → compilable crate of todo!() stubs.

- Ctx struct from ctx_schema (Option-wrapped fields, Default)
- one type alias per signature class
- CtxOp: the uniform normalized-context op type
- per item: skeleton fn + ctx wrapper (<name>_op) for module-level functions
- per group×signature class: a Vec<CtxOp> constructor (one element type per array)
- pipelines as ordered Vec<CtxOp>
"""

from __future__ import annotations

import hashlib

from spindlebox.generate.base import GeneratedFile, GeneratorBackend, GenOptions
from spindlebox.schema import Group, Item, ScaIndex

_RUST_KEYWORDS = {
    "as", "async", "await", "box", "break", "const", "continue", "crate", "dyn",
    "else", "enum", "extern", "false", "fn", "for", "if", "impl", "in", "let",
    "loop", "match", "mod", "move", "mut", "pub", "ref", "return", "static",
    "struct", "super", "trait", "true", "type", "unsafe", "use", "where", "while",
}
_NO_RAW = {"self", "Self", "super", "crate"}
# Explicit remap table for identifier edge cases real-world code produces
# (SPI policy: edge cases handled by a serialized mapping per set, not inline
# special-casing). '_' is Rust's reserved blank identifier — a param named '_'
# (Go/Rust blank, TS unused) must not surface as a bare field/binding.
_IDENT_REMAP = {
    "_": "blank",
    "": "field",
}


# Rust prelude type names a generated module must never shadow (a `pub mod Vec`
# makes every `Vec<..>` inside resolve to the module — E0573).
_PRELUDE_TYPES = {
    "Vec", "String", "Option", "Result", "Box", "Rc", "Arc", "HashMap", "HashSet",
    "BTreeMap", "BTreeSet", "Cow", "Cell", "RefCell", "Some", "None", "Ok", "Err",
}


def _mod_seg(name: str) -> str:
    """Module-path segment for a group name. A pure function of the original name
    (so both emission sites agree without sibling coordination). Plain identifiers
    pass through; prelude-type names and lossily-sanitized exotic names (e.g. Rust
    `&mut T` → `_mut__T_`) get a stable hash suffix so they neither shadow types
    nor collide (memchr #6: E0573/E0428)."""
    base = _ident(name)
    clean = name.isidentifier() and not name.startswith("r#")
    if clean and base not in _PRELUDE_TYPES:
        return base
    h = hashlib.sha256(name.encode()).hexdigest()[:6]
    safe = base.strip("_") or "g"
    return f"{safe}_{h}"


def _ident(name: str) -> str:
    if name in _IDENT_REMAP:
        return _IDENT_REMAP[name]
    out = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name)
    if out in _IDENT_REMAP:
        return _IDENT_REMAP[out]
    if set(out) == {"_"}:  # all-underscore identifiers are reserved-adjacent noise
        return "blank" + str(len(out))
    if not out or out[0].isdigit():
        out = "_" + out
    if out in _NO_RAW:
        return out + "_"
    if out in _RUST_KEYWORDS:
        return "r#" + out
    return out


def _split_top(s: str) -> list[str]:
    parts, depth, cur = [], 0, ""
    for ch in s:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur.strip())
    return parts


def rust_type(t: str) -> str:
    t = t.strip().lstrip("*")
    simple = {
        "str": "String", "bytes": "Vec<u8>", "bool": "bool", "i64": "i64",
        "f64": "f64", "unit": "()", "any": "serde_json::Value", "error": "String",
        # fn values can't cross the ctx boundary (no Default/Debug); carry as data
        "fn": "serde_json::Value",
    }
    if t in simple:
        return simple[t]
    if t.endswith(">") and "<" in t:
        base, args_s = t.split("<", 1)
        args = _split_top(args_s[:-1])
        base = base.strip()
        if base == "list" or base == "iter":
            return f"Vec<{rust_type(args[0])}>"
        if base == "map":
            return f"std::collections::HashMap<{rust_type(args[0])}, {rust_type(args[1]) if len(args) > 1 else 'serde_json::Value'}>"
        if base == "set":
            return f"std::collections::HashSet<{rust_type(args[0])}>"
        if base == "option":
            return f"Option<{rust_type(args[0])}>"
        if base == "result":
            err = rust_type(args[1]) if len(args) > 1 else "String"
            return f"Result<{rust_type(args[0])}, {err}>"
        if base == "tuple":
            if not args:
                return "()"
            return "(" + ", ".join(rust_type(a) for a in args) + ")"
    return "serde_json::Value"  # obj:<Name> and anything exotic


class RustBackend(GeneratorBackend):
    name = "rust"

    def generate(self, index: ScaIndex, options: GenOptions) -> list[GeneratedFile]:
        items = [
            i for i in index.items
            if options.group is None
            or i.group == options.group or i.group.startswith(options.group + ".")
        ]
        by_ordinal = {i.ordinal: i for i in items}
        aliases: dict[str, str] = {
            sig_id: f"Sig{n}" for n, sig_id in enumerate(sorted(index.signature_classes))
        }
        lines: list[str] = [
            "#![allow(dead_code, unused_variables, unused_mut, non_snake_case, unused_imports)]",
            f"//! Generated by SPIndlebox {index.spindlebox_version} from project "
            f"'{index.project_name}'. Bodies are todo!() stubs.",
            "",
            "#[derive(Debug)]",
            "pub enum OpError {",
            "    MissingCtxKey(&'static str),",
            "    Todo,",
            "}",
            "",
            "#[derive(Default, Debug)]",
            "pub struct Ctx {",
        ]
        for key in sorted(index.ctx_schema):
            lines.append(f"    pub {_ident(key)}: Option<{rust_type(index.ctx_schema[key])}>,")
        lines += [
            "}",
            "",
            "pub type CtxOp = Box<dyn FnMut(&mut Ctx) -> Result<(), OpError>>;",
            "",
            "// ---- signature classes (one element type per operation array) ----",
        ]
        for sig_id in sorted(index.signature_classes):
            sc = index.signature_classes[sig_id]
            params = ", ".join(rust_type(p) for p in sc["params"] if p)
            ret = sc["returns"]
            ret_s = "" if ret == "unit" else f" -> {rust_type(ret)}"
            lines.append(f"// {sig_id}")
            lines.append(f"pub type {aliases[sig_id]} = Box<dyn Fn({params}){ret_s}>;")
        lines.append("")

        generated_ops: list[tuple[str, str]] = []  # (fn path, ordinal ref) for arrays

        def emit_item(item: Item, indent: str, used: set[str]) -> list[str]:
            out: list[str] = []
            name = _ident(item.name)
            if name in used:
                name = f"{name}_o{item.ordinal}"
            used.add(name)
            doc = f" — {item.doc}" if item.doc else ""
            out.append(
                f"{indent}/// [{item.ordinal}] {item.address} "
                f"({item.file}:{item.span[0]}-{item.span[1]}, {item.language}, "
                f"{item.state_capture}→{item.rust_fn_trait}){doc}"
            )
            if item.kind in ("closure", "lambda"):
                out[-1] = out[-1].replace("///", "//")
                out.append(f"{indent}// internal item ({item.kind}) — not generated as a free fn")
                return out
            # dedupe param identifiers within this one list: distinct source params
            # can map to the same ident (e.g. two blank '_' params → 'blank') which
            # is a duplicate binding in Rust (serde_json #7, E0415)
            sig_params = [p for p in item.signature.params
                          if p.kind not in ("receiver", "kwvariadic")]
            pidents: list[str] = []
            seen_p: set[str] = set()
            for p in sig_params:
                base = _ident(p.name)
                if base == "__ctx":
                    base = "__ctx_p"
                ident = base
                n = 2
                while ident in seen_p:
                    ident = f"{base}_{n}"
                    n += 1
                seen_p.add(ident)
                pidents.append(ident)
            params = []
            if item.kind == "method":
                params.append("recv: &mut serde_json::Value")
            for p, ident in zip(sig_params, pidents, strict=True):
                params.append(f"{ident}: {rust_type(p.norm_type)}")
            ret = item.signature.returns_norm
            ret_s = "" if ret == "unit" else f" -> {rust_type(ret)}"
            out.append(f"{indent}pub fn {name}({', '.join(params)}){ret_s} {{")
            out.append(f"{indent}    todo!()")
            out.append(f"{indent}}}")
            if item.kind == "function":
                out.append("")
                out.append(f"{indent}pub fn {name}_op() -> crate::CtxOp {{")
                # the closure binding is reserved: a source param named 'ctx' (or even
                # '__ctx') must never shadow it — see issue #1
                out.append(f"{indent}    Box::new(move |__ctx: &mut crate::Ctx| {{")
                call_args = []
                for p, var in zip(sig_params, pidents, strict=True):
                    # blank/ignored params ('_') collapse in the name-keyed param_map,
                    # so routing them through ctx picks the wrong field/type
                    # (serde_json #7, E0308). They are ignored by definition → pass a
                    # default, no ctx binding.
                    if p.name == "_" or set(p.name) <= {"_"}:
                        call_args.append("Default::default()")
                        continue
                    ctx_ref = item.ctx_adapter.param_map.get(p.name, f"ctx.{p.name}")
                    key = ctx_ref.removeprefix("ctx.")
                    field = _ident(key)
                    if key in item.ctx_adapter.requires:
                        out.append(
                            f"{indent}        let {var} = __ctx.{field}.clone()"
                            f".ok_or(crate::OpError::MissingCtxKey(\"{key}\"))?;"
                        )
                    else:
                        out.append(
                            f"{indent}        let {var} = __ctx.{field}.clone().unwrap_or_default();"
                        )
                    call_args.append(var)
                # path-qualified call: a local binding (param named like the fn, or the
                # __ctx binding when the fn itself is named __ctx) can never shadow it
                out.append(
                    f"{indent}        let result = self::{name}({', '.join(call_args)});")
                if item.ctx_adapter.return_key:
                    rk = _ident(item.ctx_adapter.return_key)
                    out.append(f"{indent}        __ctx.{rk} = Some(result);")
                else:
                    out.append(f"{indent}        let _ = result;")
                out.append(f"{indent}        Ok(())")
                out.append(f"{indent}    }})")
                out.append(f"{indent}}}")
                mod_path = "::".join(_mod_seg(p) for p in item.group.split("."))
                generated_ops.append((f"crate::{mod_path}::{name}_op()", item.address))
            return out

        op_arrays: list[str] = []

        def emit_group(group: Group, indent: str) -> list[str]:
            out: list[str] = []
            gname = _mod_seg(group.name)
            out.append(f"{indent}pub mod {gname} {{")
            used: set[str] = set()
            member_items = [
                by_ordinal[o] for o in group.member_ordinals if o in by_ordinal
            ]
            for item in member_items:
                out.extend(emit_item(item, indent + "    ", used))
                out.append("")
            for child in group.children:
                out.extend(emit_group(child, indent + "    "))
            out.append(f"{indent}}}")
            # signature-homogeneous op arrays for this group
            fn_paths = {addr: path for path, addr in generated_ops}
            for n, sig_id in enumerate(sorted(group.op_arrays)):
                members = [
                    by_ordinal[o] for o in group.op_arrays[sig_id]
                    if o in by_ordinal and by_ordinal[o].kind == "function"
                ]
                refs = [fn_paths.get(m.address) for m in members]
                refs = [r for r in refs if r]
                if not refs:
                    continue
                arr_name = _ident(f"ops_{group.path.replace('.', '_')}_{n}")
                op_arrays.append(f"// {sig_id} — members: "
                                 + ", ".join(m.address for m in members))
                op_arrays.append(f"pub fn {arr_name}() -> Vec<crate::CtxOp> {{")
                op_arrays.append("    vec![" + ", ".join(refs) + "]")
                op_arrays.append("}")
            return out

        for root in index.groups:
            lines.extend(emit_group(root, ""))
            lines.append("")
        lines.append("// ---- operation groups (arrays partitioned by signature) ----")
        lines.extend(op_arrays)

        if index.pipelines:
            lines.append("")
            lines.append("// ---- ordered pipelines ----")
            fn_paths = {addr: path for path, addr in generated_ops}
            for pipe in index.pipelines:
                stages = [by_ordinal.get(o) for o in pipe.stages]
                refs = [fn_paths.get(s.address) for s in stages if s is not None]
                if not all(refs):
                    lines.append(f"// pipeline '{pipe.name}' skipped: stage(s) not generatable")
                    continue
                lines.append(f"pub fn pipeline_{_ident(pipe.name)}() -> Vec<crate::CtxOp> {{")
                lines.append("    vec![" + ", ".join(refs) + "]")
                lines.append("}")

        cargo = "\n".join([
            "[package]",
            f'name = "{_ident(index.project_name).strip("r#")}"',
            'version = "0.1.0"',
            'edition = "2021"',
            "",
            "[dependencies]",
            'serde_json = "1"',
            "",
        ])
        return [
            GeneratedFile("Cargo.toml", cargo),
            GeneratedFile("src/lib.rs", "\n".join(lines) + "\n"),
        ]
