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
    RawFnTable,
    discover_files,
    normalize_langs,
)
from spindlebox.extract.profile_registry import (
    builtins_for,
    declared_constructs,
    entry_point_reason,
    entry_points_for,
    stdlib_calls_for,
)
from spindlebox.schema import (
    CtxAdapter,
    Deps,
    FnTable,
    Group,
    Item,
    Param,
    ScaIndex,
    Signature,
)
from spindlebox.sigclass import build_signature_classes, partition_op_arrays, sig_class_id
from spindlebox.staleness import snapshot_files
from spindlebox.typenorm import normalize

#: Every marker ``build_index`` writes. See ``ScaIndex.markers``. The six after
#: ``entry_points`` are the function-as-value constructs of #39; which of them
#: each language has is in ``ScaIndex.constructs``. ``fn_tables`` says the
#: index looked for data structures holding functions (#40).
INDEX_MARKERS = ("builtin_calls", "stdlib_calls", "entry_points",
                 "decorators", "parent", "takes_fn", "returns_fn",
                 "param_calls", "table_calls", "fn_tables")

#: Call markers extraction resolves itself; ``resolve_calls`` never sees them.
_INDIRECT_CALLS = ("param:", "table:")


def _extract_file(lang: str, rel: str, source: str) -> list[RawDecl]:
    from spindlebox.extract.profile_registry import profile_for
    prof = profile_for(lang)
    if prof is not None and prof.walker:
        from spindlebox.extract.profile_lang import extract_with_profile
        return extract_with_profile(prof, rel, source, meta=True)
    if lang == "python":
        from spindlebox.extract.py_lang import extract_python_file
        return extract_python_file(rel, source, meta=True)
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


def _extract_fn_tables(lang: str, rel: str, source: str, file_decls: list[RawDecl]) -> dict:
    """``{"tables", "registrars", "registrations"}`` for one file (#40); only
    Python's native extractor finds registries."""
    from spindlebox.extract.profile_registry import profile_for
    prof = profile_for(lang)
    if prof is not None and prof.walker:
        from spindlebox.extract.profile_lang import extract_fn_tables_with_profile
        return {"tables": extract_fn_tables_with_profile(prof, rel, source),
                "registrars": [], "registrations": []}
    if lang == "python":
        from spindlebox.extract.py_lang import extract_python_fn_tables
        return extract_python_fn_tables(rel, source, file_decls)
    return {"tables": [], "registrars": [], "registrations": []}


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
    with_source: bool = False,
) -> ScaIndex:
    """Build an SPI for `root`.

    `with_source` additionally stores each item's verbatim body on the item. Off by
    default: it roughly doubles index size and only body translation (#21) reads it.
    The body is always *locatable* via `file`+`span` regardless; this controls whether
    it is *captured*.
    """
    root = Path(root).resolve()
    project_name = project_name or root.name
    lang_list = normalize_langs(langs)

    decls: list[RawDecl] = []
    errors: list[str] = []
    # every file we actually read, so staleness can be checked later (#15).
    # a file that failed to parse still counts: it was read, and a later edit
    # to it is exactly the change a caller needs to know about.
    read_files: list[str] = []
    raw_fn: dict[str, list] = {"tables": [], "registrars": [], "registrations": []}
    for rel, lang in discover_files(root, lang_list):
        try:
            source = (root / rel).read_text(errors="replace")
        except OSError as e:
            errors.append(f"{rel}: unreadable ({e})")
            continue
        read_files.append(rel)
        try:
            file_decls = _extract_file(lang, rel, source)
            found = _extract_fn_tables(lang, rel, source, file_decls)
        except SyntaxError as e:
            errors.append(f"{rel}: parse failed ({e})")
            continue
        decls.extend(file_decls)
        for k, v in found.items():
            raw_fn[k].extend(v)
    # the entry points a Python package declares are tables too (#40)
    pyproject = root / "pyproject.toml"
    if "python" in lang_list and pyproject.is_file():
        from spindlebox.extract.py_lang import pyproject_fn_tables
        try:
            entry_tables = pyproject_fn_tables(pyproject.read_text(errors="replace"))
        except OSError:
            entry_tables = []
        raw_fn["tables"].extend(entry_tables)
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
    address_of: dict[int, str] = {}      # id(RawDecl) -> address, for parent/table
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
        address_of[id(d)] = address

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
            # `hash` above is taken over this same text, so staleness detection
            # already vouches for it — no separate integrity path needed.
            source_text=d.body_text if with_source else None,
            entry_point=entry_point_reason(entry_points_for(d.language), d.name, d.file),
            decorators=list(d.decorators),
            takes_fn=d.takes_fn,
            returns_fn=d.returns_fn,
        )
        raw_calls[address] = d.calls
        items.append(item)

    # a nested item's parent, and the address of each table a call goes through,
    # can only be named once every address is known (#39)
    for d, item in zip(decls, items, strict=True):
        if d.parent is not None:
            item.parent = address_of.get(id(d.parent))
        raw_calls[item.address] = [
            _table_address(c, d, item, address_of) if c.startswith("table:") else c
            for c in raw_calls[item.address]]

    old_map = {i.address: i.ordinal for i in old_index.items} if old_index else {}
    old_retired = list(old_index.retired_ordinals) if old_index else []
    retired = assign_ordinals(items, old_map, old_retired)

    # intra-index call resolution
    addresses_by_name: dict[str, list[str]] = {}
    for item in items:
        addresses_by_name.setdefault(item.name, []).append(item.address)
    for item in items:
        raw = raw_calls[item.address]
        item.deps.calls = resolve_calls(
            [c for c in raw if not c.startswith(_INDIRECT_CALLS)], item.group,
            addresses_by_name, builtins=builtins_for(item.language),
        ) + list(dict.fromkeys(c for c in raw if c.startswith(_INDIRECT_CALLS)))
        stdlib = stdlib_calls_for(item.language)
        item.deps.stdlib_calls = sorted({
            c[len("external:"):] for c in item.deps.calls
            if c.startswith("external:") and c[len("external:"):] in stdlib})

    ctx_schema = apply_ctx_normalization(items)
    signature_classes = build_signature_classes(items)
    groups = _build_groups(items)

    fn_tables = _resolve_fn_tables(raw_fn, items, address_of)
    if any(t.file not in read_files for t in fn_tables):
        # a table's span must be staleness-checkable like an item's
        read_files += sorted({t.file for t in fn_tables} - set(read_files))
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
        files=snapshot_files(root, read_files),
        # the neutral markers this build wrote; `gaps` trusts only what is listed (#38)
        markers=list(INDEX_MARKERS),
        constructs={lang: declared_constructs(lang)
                    for lang in sorted({i.language for i in items})},
        fn_tables=fn_tables,
    )
    if errors:
        index.parse_errors = errors  # serialized: an index must never hide skipped files
    return index


def _table_address(call: str, d: RawDecl, item: Item, address_of: dict[int, str]) -> str:
    """``table:<name>`` -> ``table:<address of the table>``, from where extraction
    found ``<name>`` declared: an item (``<item address>.<name>``), the receiver
    (``<module>.<class chain>.<rest>``) or, failing both, the module."""
    name = call[len("table:"):]
    where, owner = d.table_scopes.get(call, ("module", None))
    if where == "item" and owner is not None and id(owner) in address_of:
        return f"table:{address_of[id(owner)]}.{name}"
    if where == "receiver":
        rest = name.split(".", 1)[1] if "." in name else name
        return "table:" + ".".join([*module_parts(d.file), *d.class_chain, rest])
    return "table:" + ".".join([*module_parts(d.file), name])


def _member_resolver(items: list[Item], address_of: dict[int, str]):
    """``resolve(ref, file, qualified) -> address | None`` for a table member.

    A ``RawDecl`` is its own address. A qualified path (``pkg.mod.f``) matches an
    address exactly or as a suffix. A name as written in ``file`` is the item of
    that name defined there -- the top-level one if several -- else the only item
    of that name in the index; ``mod.f`` must match an address suffix. Anything
    else (a constant, a builtin, an ambiguous name) is not a member.
    """
    addresses = {i.address for i in items}
    by_name: dict[str, list[Item]] = {}
    for i in items:
        by_name.setdefault(i.name, []).append(i)

    def by_suffix(path: str) -> str | None:
        if path in addresses:
            return path
        hits = [a for a in addresses if a.endswith("." + path)]
        return hits[0] if len(hits) == 1 else None

    def resolve(ref, file: str, qualified: bool = False) -> str | None:
        if isinstance(ref, RawDecl):
            return address_of.get(id(ref))
        if qualified or "." in ref:
            return by_suffix(ref)
        named = by_name.get(ref, [])
        local = [i for i in named if i.file == file]
        top = [i for i in local if i.parent is None and i.kind != "method"]
        for pool in (top, local, named):
            if len(pool) == 1:
                return pool[0].address
        return None

    return resolve


def _resolve_fn_tables(raw: dict, items: list[Item], address_of: dict[int, str]) -> list[FnTable]:
    """Raw tables, registrars and registrations -> ``FnTable``s whose members are
    item addresses (#40). A registration is paired with the registrar it names
    (by its last dotted segment; same file first when the name is not unique) and
    adds its function to that registrar's table. Tables with no member that is
    an item are dropped: a dict of strings is not a table of functions."""
    resolve = _member_resolver(items, address_of)

    def address(t: RawFnTable) -> str:
        return t.address or ".".join([*module_parts(t.file), *t.scope_chain, t.name])

    tables: dict[str, RawFnTable] = {}
    for t in raw["tables"]:
        tables[address(t)] = t
    literal_members = {a: bool(t.members) for a, t in tables.items()}

    registrars: dict[str, list[dict]] = {}
    for r in raw["registrars"]:
        registrars.setdefault(r["name"], []).append(r)
    added: dict[str, list] = {}
    for g in sorted(raw["registrations"], key=lambda g: (g["file"], g["line"])):
        cands = registrars.get(g["head"].rsplit(".", 1)[-1], [])
        if len(cands) > 1:
            cands = [r for r in cands if r["file"] == g["file"]]
        if len(cands) != 1:
            continue
        r = cands[0]
        member = None
        if g["mode"] == "factory" and r["mode"] == "factory":
            member = g["member"]
        elif g["mode"] == "direct" and r["mode"] == "direct" and r["index"] == 0:
            member = g["member"]
        elif g["mode"] == "call" and r["mode"] == "direct":
            args = g["args"]
            idx = r["index"]
            member = args[idx] if idx is not None and idx < len(args) else None
            member = member or g["kwargs"].get(r["param"])
        if member is None:
            continue
        key = ".".join([*module_parts(r["file"]), r["table"]])
        if key not in tables:
            tables[key] = RawFnTable(
                name=r["table"], file=r["file"], start_line=r["start_line"],
                end_line=r["end_line"], kind="registry", key_type=r["key_type"])
            literal_members[key] = False
        if not literal_members[key]:
            tables[key].kind, tables[key].key_type = "registry", r["key_type"]
        added.setdefault(key, []).append((member, g["file"]))

    out: list[FnTable] = []
    for key, t in tables.items():
        members: list[str] = []
        refs = [(m, t.file) for m in t.members] + added.get(key, [])
        for ref, file in refs:
            a = resolve(ref, file, t.qualified)
            if a is not None and a not in members:
                members.append(a)
        if members:
            out.append(FnTable(address=key, file=t.file, span=(t.start_line, t.end_line),
                               kind=t.kind, members=members, key_type=t.key_type))
    out.sort(key=lambda t: (t.file, t.span[0], t.address))
    return out


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
