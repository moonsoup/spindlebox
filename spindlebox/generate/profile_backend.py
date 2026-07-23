"""Profile-driven emit engine: SPI index → skeleton code in any target language.

The emission algorithm (ctx container → signature aliases → group tree with
skeletons and ctx wrappers → op arrays → pipelines) is language-independent
engine logic. Everything language-specific — identifier rules, the core-1 →
target type table, and the code-line templates — lives in a JSON emit profile
(``generate/emit_profiles/<lang>.json``). Adding an output language should
normally mean adding one emit profile, no new backend module.

Templates use ``string.Template`` (``${var}``) so literal braces in generated
code need no escaping. Type-table formats use ``str.format`` (``{0}``/``{1}``)
since type strings contain no literal braces.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from string import Template

from spindlebox.generate.base import (
    GeneratedFile,
    GeneratorBackend,
    GenOptions,
    flatten_block,
    squeeze_blanks,
)
from spindlebox.generate.rust_backend import _split_top
from spindlebox.schema import Group, Item, ScaIndex

EMIT_DIR = Path(__file__).parent / "emit_profiles"

_PLACEHOLDER = re.compile(r"\{(\d+)\}")


def _sub(tpl: str, **vars) -> str:
    return Template(tpl).substitute(vars)


def _sub_all(tpls: list[str], **vars) -> list[str]:
    return [_sub(t, **vars) for t in tpls]


class EmitProfile:
    def __init__(self, data: dict):
        self.data = data
        ident = data["ident"]
        self.keywords = set(ident.get("keywords", []))
        self.no_raw = set(ident.get("no_raw", []))
        self.remap = ident.get("remap", {})
        self.escape = ident.get("escape", {"style": "suffix", "with": "_"})
        self.reserved_types = set(ident.get("reserved_type_names", []))
        self.reserve_root = bool(ident.get("reserve_root_name"))
        self.reserve_aliases = bool(ident.get("reserve_alias_names"))
        # e.g. Java: a nested class may not share the simple name of any enclosing class
        self.reserve_ancestors = bool(ident.get("reserve_ancestor_names"))
        # e.g. Java: a static member may not hide an Object instance method
        # (clone, toString, …) — escape these item names like keywords
        self.reserved_members = set(ident.get("reserved_member_names", []))
        # e.g. Java: no let-shadowing — the wrapper's result binding must not
        # collide with a source param named 'result'
        self.unique_result = bool(ident.get("unique_result_binding"))
        self.types = data["types"]
        self.t = data["templates"]
        self.files = data["files"]

    # mirror of rust_backend._ident, parameterized
    def ident(self, name: str) -> str:
        if name in self.remap:
            return self.remap[name]
        out = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name)
        if out in self.remap:
            return self.remap[out]
        if set(out) == {"_"}:
            return "blank" + str(len(out))
        if not out or out[0].isdigit():
            out = "_" + out
        if out in self.no_raw:
            return out + "_"
        if out in self.keywords:
            if self.escape["style"] == "prefix":
                return self.escape["with"] + out
            return out + self.escape["with"]
        return out

    # mirror of rust_backend._mod_seg, parameterized
    def mod_seg(self, name: str, extra_reserved: frozenset | set = frozenset()) -> str:
        base = self.ident(name)
        prefix = self.escape["with"] if self.escape["style"] == "prefix" else None
        clean = name.isidentifier() and not (prefix and name.startswith(prefix))
        if clean and base not in self.reserved_types and base not in extra_reserved:
            return base
        h = hashlib.sha256(name.encode()).hexdigest()[:6]
        safe = base.strip("_") or "g"
        if not safe[0].isalpha():
            safe = "g" + safe
        return f"{safe}_{h}"

    def mod_path_segs(self, path: str, extra_reserved: set[str]) -> list[str]:
        """Emitted segment names for a dotted group path. When the profile forbids
        ancestor shadowing, each segment also reserves the segments above it, so
        both emission sites (module tree and wrapper paths) agree by construction."""
        segs: list[str] = []
        for part in path.split("."):
            reserved = extra_reserved | set(segs) if self.reserve_ancestors else extra_reserved
            segs.append(self.mod_seg(part, reserved))
        return segs

    # mirror of rust_backend.rust_type, table-driven
    def render_type(self, t: str) -> str:
        t = t.strip().lstrip(self.types.get("strip_leading", ""))
        simple = self.types["simple"]
        if t in simple:
            return simple[t]
        if t.endswith(">") and "<" in t:
            base, args_s = t.split("<", 1)
            spec = self.types["containers"].get(base.strip())
            if spec:
                args = _split_top(args_s[:-1])
                if spec.get("variadic"):
                    if not args:
                        return spec["empty"]
                    joined = spec.get("join", ", ").join(self.render_type(a) for a in args)
                    return spec["format"].replace("{args}", joined)
                fmt = spec["format"]
                need = max((int(m) for m in _PLACEHOLDER.findall(fmt)), default=-1) + 1
                defaults = spec.get("defaults", [])
                vals = [
                    self.render_type(args[i] if i < len(args) else defaults[i])
                    for i in range(need)
                ]
                return fmt.format(*vals)
        return self.types["fallback"]


class ProfileBackend(GeneratorBackend):
    """Generic backend; concrete per-language classes are built by load_emit_backends()."""

    name = ""
    profile_path: Path

    def __init__(self):
        self.p = EmitProfile(json.loads(self.profile_path.read_text()))

    def generate(self, index: ScaIndex, options: GenOptions) -> list[GeneratedFile]:
        p = self.p
        T = p.t
        items = [
            i for i in index.items
            if options.group is None
            or i.group == options.group or i.group.startswith(options.group + ".")
        ]
        by_ordinal = {i.ordinal: i for i in items}
        aliases: dict[str, str] = {
            sig_id: f"Sig{n}" for n, sig_id in enumerate(sorted(index.signature_classes))
        }
        base_name = p.ident(index.project_name)
        root = (base_name[0].upper() + base_name[1:]) if base_name[:1].isalpha() else "G" + base_name
        gvars = {
            "version": index.spindlebox_version,
            "project": index.project_name,
            "root": root,
            # legacy Cargo-name expression preserved verbatim for byte parity
            "crate_name": p.ident(index.project_name).strip("r#"),
        }
        extra_reserved: set[str] = set()
        if p.reserve_root:
            extra_reserved.add(root)
        if p.reserve_aliases:
            extra_reserved.update(aliases.values())

        lines = _sub_all(T["header"], **gvars)

        # injective ctx-key → field-ident map (same construction as rust_backend);
        # spindle_trace is reserved for the built-in workflow tracker
        ctx_fields: dict[str, str] = {}
        used_fields: set[str] = {"spindle_trace"}
        for key in sorted(index.ctx_schema):
            base = p.ident(key)
            ident = base
            n = 2
            while ident in used_fields:
                ident = f"{base}_{n}"
                n += 1
            used_fields.add(ident)
            ctx_fields[key] = ident
        for key in sorted(index.ctx_schema):
            lines.append(_sub(T["ctx_field"], field=ctx_fields[key],
                              type=p.render_type(index.ctx_schema[key]), **gvars))
        lines.append(_sub(T["ctx_trace_field"], **gvars))
        lines += _sub_all(T["after_ctx"], **gvars)

        for sig_id in sorted(index.signature_classes):
            sc = index.signature_classes[sig_id]
            filtered = [q for q in sc["params"] if q]
            params = ", ".join(
                _sub(T["alias_param"], type=p.render_type(q), i=str(i))
                for i, q in enumerate(filtered)
            )
            ret = sc["returns"]
            ret_s = T["alias_ret_unit"] if ret == "unit" else \
                _sub(T["alias_ret"], type=p.render_type(ret))
            lines += _sub_all(T["sig_alias"], sig_id=sig_id, alias=aliases[sig_id],
                              params=params, ret=ret_s, **gvars)
        lines += T.get("after_aliases", [])

        generated_ops: list[tuple[str, str]] = []
        module_sep = T["module_sep"]
        ctx_binding = T.get("ctx_binding", "__ctx")

        def emit_item(item: Item, indent: str, used: set[str]) -> list[str]:
            out: list[str] = []
            name = p.ident(item.name)
            if name in p.reserved_members:
                name = name + (p.escape["with"] if p.escape["style"] == "suffix" else "_")
            if name in used:
                name = f"{name}_o{item.ordinal}"
            used.add(name)
            doc_sfx = ""
            if item.doc:
                doc = item.doc
                for old, new in T.get("doc_escape", {}).items():
                    doc = doc.replace(old, new)
                doc_sfx = _sub(T["doc_suffix"], doc=doc)
            ivars = {
                "indent": indent, "ordinal": str(item.ordinal), "address": item.address,
                "file": item.file, "start": str(item.span[0]), "end": str(item.span[1]),
                "language": item.language, "state": item.state_capture,
                "trait": item.rust_fn_trait, "docsuffix": doc_sfx, "name": name, **gvars,
            }
            if item.kind in ("closure", "lambda"):
                out.append(_sub(T["item_doc_internal"], **ivars))
                out += _sub_all(T["internal_note"], kind=item.kind, **ivars)
                return out
            out.append(_sub(T["item_doc"], **ivars))
            sig_params = [q for q in item.signature.params
                          if q.kind not in ("receiver", "kwvariadic")]
            pidents: list[str] = []
            seen_p: set[str] = set()
            for q in sig_params:
                base = p.ident(q.name)
                if base == ctx_binding:
                    base = ctx_binding + "_p"
                ident = base
                n = 2
                while ident in seen_p:
                    ident = f"{base}_{n}"
                    n += 1
                seen_p.add(ident)
                pidents.append(ident)
            params = []
            if item.kind == "method":
                params.append(T["receiver_param"])
            for q, pid in zip(sig_params, pidents, strict=True):
                params.append(_sub(T["param"], ident=pid, type=p.render_type(q.norm_type)))
            ret = item.signature.returns_norm
            is_unit = ret == "unit"
            ret_s = T["skeleton_ret_unit"] if is_unit else \
                _sub(T["skeleton_ret"], type=p.render_type(ret))
            skeleton = [_sub(T["skeleton_open"], params=", ".join(params), ret=ret_s, **ivars)]
            skeleton += _sub_all(T["skeleton_body"], **ivars)
            skeleton.append(_sub(T["skeleton_close"], **ivars))
            out.extend(skeleton if options.pretty else flatten_block(skeleton))
            if item.kind == "function":
                mod_path = module_sep.join(p.mod_path_segs(item.group, extra_reserved))
                wvars = {**ivars, "mod_path": mod_path}
                opened = _sub_all(T["wrapper_open"], **wvars)
                sep, wrapper = (opened[0], opened[1:]) if opened and opened[0] == "" \
                    else ("", opened)
                wrapper.append(_sub(T["wrapper_trace"], **wvars))
                out, real_out = wrapper, out
                call_args = []
                for q, var in zip(sig_params, pidents, strict=True):
                    if q.name == "_" or set(q.name) <= {"_"}:
                        call_args.append(T["blank_arg"])
                        continue
                    ctx_ref = item.ctx_adapter.param_map.get(q.name, f"ctx.{q.name}")
                    key = ctx_ref.removeprefix("ctx.")
                    field = ctx_fields.get(key, p.ident(key))
                    tpl = T["fetch_required"] if key in item.ctx_adapter.requires \
                        else T["fetch_optional"]
                    out += _sub_all(tpl, var=var, field=field, key=key,
                                    type=p.render_type(q.norm_type), **wvars)
                    call_args.append(var)
                args_s = ", ".join(call_args)
                result_var = "result"
                if p.unique_result:
                    n = 2
                    while result_var in seen_p:
                        result_var = f"result_{n}"
                        n += 1
                if is_unit and "call_void" in T:
                    out.append(_sub(T["call_void"], args=args_s, **wvars))
                else:
                    out.append(_sub(T["call"], args=args_s, result=result_var, **wvars))
                    rk_key = item.ctx_adapter.return_key
                    if rk_key:
                        rk = ctx_fields.get(rk_key, p.ident(rk_key))
                        rktype = p.render_type(index.ctx_schema.get(rk_key, "any"))
                        out.append(_sub(T["store"], rk=rk, rktype=rktype,
                                        result=result_var, **wvars))
                    else:
                        out += _sub_all(T["discard"], result=result_var, **wvars)
                out += _sub_all(T["wrapper_close"], **wvars)
                out, wrapper = real_out, out
                if options.pretty:
                    if sep == "":
                        out.append("")
                    out.extend(wrapper)
                else:
                    out.extend(flatten_block(wrapper))
                generated_ops.append((_sub(T["op_ref"], **wvars), item.address))
            return out

        op_arrays: list[str] = []
        set_names: list[str] = []  # load order for the master spindle

        def emit_group(group: Group, indent: str, ancestors: tuple[str, ...] = ()) -> list[str]:
            out: list[str] = []
            reserved = extra_reserved | set(ancestors) if p.reserve_ancestors else extra_reserved
            gname = p.mod_seg(group.name, reserved)
            out.append(_sub(T["module_open"], indent=indent, name=gname, **gvars))
            used: set[str] = set()
            member_items = [
                by_ordinal[o] for o in group.member_ordinals if o in by_ordinal
            ]
            for item in member_items:
                out.extend(emit_item(item, indent + "    ", used))
                out.append("")
            for child in group.children:
                out.extend(emit_group(child, indent + "    ", (*ancestors, gname)))
            out.append(_sub(T["module_close"], indent=indent, **gvars))
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
                arr_name = p.ident(f"ops_{group.path.replace('.', '_')}_{n}")
                set_names.append(arr_name)
                op_arrays.append(_sub(T["array_comment"], sig_id=sig_id,
                                      members=", ".join(m.address for m in members), **gvars))
                block = [_sub(T["array_open"], name=arr_name, **gvars),
                         _sub(T["array_body"], refs=", ".join(refs), **gvars),
                         _sub(T["array_close"], **gvars)]
                op_arrays.extend(block if options.pretty else flatten_block(block))
            return out

        for root_group in index.groups:
            lines.extend(emit_group(root_group, T.get("base_indent", "")))
            lines.append("")
        lines += _sub_all(T["arrays_header"], **gvars)
        lines.extend(op_arrays)

        if index.pipelines:
            lines += _sub_all(T["pipelines_header"], **gvars)
            fn_paths = {addr: path for path, addr in generated_ops}
            for pipe in index.pipelines:
                stages = [by_ordinal.get(o) for o in pipe.stages]
                refs = [fn_paths.get(s.address) for s in stages if s is not None]
                if not all(refs):
                    lines.append(_sub(T["pipeline_skip"], name=pipe.name, **gvars))
                    continue
                # data-flow edges — a direct chain without them never composes
                from spindlebox.validate import pipeline_edges
                edges = pipe.edges or pipeline_edges([s for s in stages if s])
                by_after: dict[int, list[dict]] = {}
                for e in edges:
                    by_after.setdefault(e["after"], []).append(e)
                elems: list[str] = []
                for stage, ref in zip(stages, refs, strict=True):
                    elems.append(ref)
                    for e in by_after.get(stage.ordinal, ()):
                        elems.append(_sub(
                            T["pipeline_edge_op"],
                            src=ctx_fields.get(e["from_key"], p.ident(e["from_key"])),
                            dst=ctx_fields.get(e["to_key"], p.ident(e["to_key"])),
                            dsttype=p.render_type(index.ctx_schema.get(e["to_key"], "any")),
                            **gvars))
                pipe_fn = "pipeline_" + p.ident(pipe.name)
                set_names.append(pipe_fn)
                block = [_sub(T["pipeline_open"], name=p.ident(pipe.name), **gvars),
                         _sub(T["pipeline_body"], refs=", ".join(elems), **gvars),
                         _sub(T["pipeline_close"], **gvars)]
                lines.extend(block if options.pretty else flatten_block(block))
        lines.append("")
        lines += _sub_all(T["master_header"], **gvars)
        block = _sub_all(T["master_open"], **gvars)
        block += [_sub(T["master_entry"], name=n, **gvars) for n in set_names]
        block += _sub_all(T["master_close"], **gvars)
        lines.extend(block if options.pretty else flatten_block(block))
        lines += T.get("footer", [])
        lines = squeeze_blanks(lines)

        out_files: list[GeneratedFile] = []
        for f in self.p.files:
            if f["kind"] == "manifest":
                out_files.append(GeneratedFile(
                    _sub(f["path"], **gvars),
                    "\n".join(_sub_all(f["lines"], **gvars)) + "\n"))
            else:
                out_files.append(GeneratedFile(
                    _sub(f["path"], **gvars), "\n".join(lines) + "\n"))
        return out_files


def load_emit_backends() -> dict[str, type[ProfileBackend]]:
    out: dict[str, type[ProfileBackend]] = {}
    if EMIT_DIR.is_dir():
        for path in sorted(EMIT_DIR.glob("*.json")):
            lang = json.loads(path.read_text())["language"]
            cls = type(f"{lang.title()}ProfileBackend", (ProfileBackend,),
                       {"name": lang, "profile_path": path})
            out[lang] = cls
    return out
