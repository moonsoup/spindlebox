"""Extraction orchestrator: source tree → ScaIndex."""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

import spindlebox
from spindlebox.addresses import assign_ordinals, make_address, module_parts
from spindlebox.ctxnorm import apply_ctx_normalization
from spindlebox.depmap import external_packages, find_env_vars, resolve_calls
from spindlebox.extract.base import (
    STATE_TO_TRAIT,
    RawDecl,
    discover_files,
    normalize_langs,
)
from spindlebox.schema import CtxAdapter, Deps, Group, Item, Param, ScaIndex, Signature
from spindlebox.sigclass import build_signature_classes, partition_op_arrays, sig_class_id
from spindlebox.typenorm import normalize


def _extract_file(lang: str, rel: str, source: str) -> list[RawDecl]:
    if lang == "python":
        from spindlebox.extract.py_lang import extract_python_file
        return extract_python_file(rel, source)
    if lang in ("javascript", "typescript"):
        from spindlebox.extract.js_lang import extract_js_file
        return extract_js_file(rel, source, lang)
    if lang == "go":
        from spindlebox.extract.go_lang import extract_go_file
        return extract_go_file(rel, source)
    if lang == "rust":
        from spindlebox.extract.rust_lang import extract_rust_file
        return extract_rust_file(rel, source)
    if lang == "bash":
        from spindlebox.extract.bash_lang import extract_bash_file
        return extract_bash_file(rel, source)
    raise ValueError(f"no extractor for language '{lang}'")


def _norm_param_type(p_raw: str | None, kind: str, language: str) -> str:
    if kind == "variadic":
        elem = normalize(p_raw, language) if p_raw else "any"
        if language == "bash":
            elem = "str"
        return f"list<{elem}>"
    if kind == "kwvariadic":
        return "map<str,any>"
    if kind == "receiver":
        return normalize(p_raw, language) if p_raw else "any"
    return normalize(p_raw, language)


def build_index(
    root: str | Path,
    project_name: str | None = None,
    langs: list[str] | None = None,
    old_index: ScaIndex | None = None,
) -> ScaIndex:
    root = Path(root).resolve()
    project_name = project_name or root.name
    lang_list = normalize_langs(langs)

    decls: list[RawDecl] = []
    errors: list[str] = []
    for rel, lang in discover_files(root, lang_list):
        try:
            source = (root / rel).read_text(errors="replace")
        except OSError as e:
            errors.append(f"{rel}: unreadable ({e})")
            continue
        try:
            decls.extend(_extract_file(lang, rel, source))
        except SyntaxError as e:
            errors.append(f"{rel}: parse failed ({e})")
    decls.sort(key=lambda d: (d.file, d.start_line, d.name))

    # local top-level roots (for external-package classification)
    local_roots: set[str] = set()
    for d in decls:
        parts = module_parts(d.file)
        if parts:
            local_roots.add(parts[0])

    items: list[Item] = []
    raw_calls: dict[str, list[str]] = {}
    used_addresses: set[str] = set()
    for d in decls:
        address = make_address(d.file, d.scope_chain, d.name, d.start_line)
        if address in used_addresses:
            # multiple anonymous items can share a line (e.g. two lambdas on one
            # line); append an incrementing counter so addresses stay unique —
            # appending the (identical) line number did not disambiguate and
            # produced duplicate ordinals (pydantic T3, #8)
            n = 2
            while f"{address}~{n}" in used_addresses:
                n += 1
            address = f"{address}~{n}"
        used_addresses.add(address)

        params = [
            Param(
                name=p.name,
                raw_type=p.raw_type,
                norm_type=_norm_param_type(p.raw_type, p.kind, d.language),
                default=p.default,
                kind=p.kind,
            )
            for p in d.params
        ]
        returns_norm = d.returns_norm or normalize(d.returns_raw, d.language)
        sig = Signature(
            params=params, returns_raw=d.returns_raw,
            returns_norm=returns_norm, is_async=d.is_async,
        )
        group_path = ".".join(module_parts(d.file) + d.class_chain)
        item = Item(
            ordinal=-1,
            address=address,
            name=d.name if not d.name.startswith("<") else address.rsplit(".", 1)[-1],
            kind=d.kind,
            language=d.language,
            file=d.file,
            span=(d.start_line, d.end_line),
            group=group_path,
            signature=sig,
            sig_class=sig_class_id(sig),
            state_capture=d.state_capture,
            rust_fn_trait=STATE_TO_TRAIT[d.state_capture],
            ctx_adapter=CtxAdapter(requires={}, provides={}, param_map={}, return_key=None),
            deps=Deps(
                imports=sorted(set(d.imports)),
                external_packages=external_packages(d.imports, d.language, local_roots),
                env_vars=find_env_vars(d.body_text, d.language),
            ),
            doc=d.doc,
            hash="sha256:" + hashlib.sha256(d.body_text.encode()).hexdigest()[:16],
        )
        raw_calls[address] = d.calls
        items.append(item)

    old_map = {i.address: i.ordinal for i in old_index.items} if old_index else {}
    old_retired = list(old_index.retired_ordinals) if old_index else []
    retired = assign_ordinals(items, old_map, old_retired)

    # intra-index call resolution
    addresses_by_name: dict[str, list[str]] = {}
    for item in items:
        addresses_by_name.setdefault(item.name, []).append(item.address)
    for item in items:
        item.deps.calls = resolve_calls(raw_calls[item.address], item.group, addresses_by_name)

    ctx_schema = apply_ctx_normalization(items)
    signature_classes = build_signature_classes(items)
    groups = _build_groups(items)

    index = ScaIndex(
        project_name=project_name,
        root=str(root),
        generated_at=datetime.now().isoformat(timespec="seconds"),
        spindlebox_version=spindlebox.__version__,
        items=sorted(items, key=lambda i: i.ordinal),
        groups=groups,
        signature_classes=signature_classes,
        pipelines=list(old_index.pipelines) if old_index else [],
        ctx_schema=ctx_schema,
        retired_ordinals=retired,
    )
    if errors:
        index.parse_errors = errors  # advisory, not serialized
    return index


def _build_groups(items: list[Item]) -> list[Group]:
    groups_by_path: dict[str, Group] = {}
    roots: list[Group] = []

    def ensure(path: str, kind: str) -> Group:
        if path in groups_by_path:
            return groups_by_path[path]
        g = Group(
            name=path.rsplit(".", 1)[-1], kind=kind, path=path,
            member_ordinals=[], op_arrays={}, children=[],
        )
        groups_by_path[path] = g
        if "." in path:
            parent = ensure(path.rsplit(".", 1)[0], "package")
            parent.children.append(g)
        else:
            roots.append(g)
        return g

    for item in sorted(items, key=lambda i: i.ordinal):
        module = module_parts(item.file)
        for depth in range(1, len(module)):
            ensure(".".join(module[:depth]), "package")
        module_path = ".".join(module)
        if module_path:
            ensure(module_path, "module")
        class_path = module_path
        n_classes = len(item.group.split(".")) - len(module) if item.group else 0
        class_chain = item.group.split(".")[len(module):] if n_classes > 0 else []
        for cls in class_chain:
            class_path = f"{class_path}.{cls}" if class_path else cls
            ensure(class_path, "class")
        if item.group:
            ensure(item.group, "module").member_ordinals.append(item.ordinal)

    items_by_ordinal = {i.ordinal: i for i in items}
    for g in groups_by_path.values():
        partition_op_arrays(g, items_by_ordinal)
    return roots
