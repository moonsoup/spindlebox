"""SCA data model: dataclasses, JSON serialization, structural validation."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from spindlebox import SPI_VERSION, TYPE_VOCABULARY

ITEM_KINDS = {"function", "method", "closure", "lambda", "script_main"}
PARAM_KINDS = {"positional", "keyword", "variadic", "kwvariadic", "receiver"}
STATE_CAPTURES = {
    "pure", "reads_captured", "mutates_captured", "consumes",
    "reads_instance", "mutates_instance",
}
FN_TRAITS = {"fn", "Fn", "FnMut", "FnOnce"}
GROUP_KINDS = {"package", "module", "class"}


class SchemaError(Exception):
    """Raised when an index document does not conform to the SCA schema."""


def _req(d: dict, key: str, ctx: str) -> Any:
    if key not in d:
        raise SchemaError(f"missing required field '{key}' in {ctx}")
    return d[key]


def _enum(value: str, allowed: set[str], field_name: str, ctx: str) -> str:
    if value not in allowed:
        raise SchemaError(f"invalid {field_name} '{value}' in {ctx} (allowed: {sorted(allowed)})")
    return value


@dataclass
class Param:
    name: str
    raw_type: str | None
    norm_type: str
    default: str | None
    kind: str  # PARAM_KINDS

    def to_dict(self) -> dict:
        return {
            "name": self.name, "raw_type": self.raw_type, "norm_type": self.norm_type,
            "default": self.default, "kind": self.kind,
        }

    @classmethod
    def from_dict(cls, d: dict, ctx: str) -> Param:
        return cls(
            name=_req(d, "name", ctx),
            raw_type=d.get("raw_type"),
            norm_type=_req(d, "norm_type", ctx),
            default=d.get("default"),
            kind=_enum(_req(d, "kind", ctx), PARAM_KINDS, "param kind", ctx),
        )


@dataclass
class Signature:
    params: list[Param]
    returns_raw: str | None
    returns_norm: str
    is_async: bool = False

    def to_dict(self) -> dict:
        return {
            "params": [p.to_dict() for p in self.params],
            "returns": {"raw_type": self.returns_raw, "norm_type": self.returns_norm},
            "is_async": self.is_async,
        }

    @classmethod
    def from_dict(cls, d: dict, ctx: str) -> Signature:
        returns = _req(d, "returns", ctx)
        return cls(
            params=[Param.from_dict(p, ctx) for p in _req(d, "params", ctx)],
            returns_raw=returns.get("raw_type"),
            returns_norm=_req(returns, "norm_type", ctx),
            is_async=bool(d.get("is_async", False)),
        )


@dataclass
class CtxAdapter:
    requires: dict[str, str]
    provides: dict[str, str]
    param_map: dict[str, str]
    return_key: str | None

    def to_dict(self) -> dict:
        return {
            "requires": self.requires, "provides": self.provides,
            "param_map": self.param_map, "return_key": self.return_key,
        }

    @classmethod
    def from_dict(cls, d: dict, ctx: str) -> CtxAdapter:
        return cls(
            requires=dict(_req(d, "requires", ctx)),
            provides=dict(_req(d, "provides", ctx)),
            param_map=dict(_req(d, "param_map", ctx)),
            return_key=d.get("return_key"),
        )


@dataclass
class Deps:
    calls: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    external_packages: list[str] = field(default_factory=list)
    env_vars: list[str] = field(default_factory=list)
    ctx_keys_required: list[str] = field(default_factory=list)
    #: Bare names among ``calls`` that the language's standard library supplies
    #: (its profile's ``stdlib_calls``). The edge stays ``external:`` -- the code
    #: is outside the project -- but a reader can tell it from a typo without
    #: knowing the language (#38). Omitted when empty, so older indexes and
    #: languages that declare none are unchanged on disk.
    stdlib_calls: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
            "calls": self.calls, "imports": self.imports,
            "external_packages": self.external_packages, "env_vars": self.env_vars,
            "ctx_keys_required": self.ctx_keys_required,
        }
        if self.stdlib_calls:
            d["stdlib_calls"] = self.stdlib_calls
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Deps:
        return cls(
            calls=list(d.get("calls", [])),
            imports=list(d.get("imports", [])),
            external_packages=list(d.get("external_packages", [])),
            env_vars=list(d.get("env_vars", [])),
            ctx_keys_required=list(d.get("ctx_keys_required", [])),
            stdlib_calls=list(d.get("stdlib_calls", [])),
        )


@dataclass
class Item:
    ordinal: int
    address: str
    name: str
    kind: str  # ITEM_KINDS
    language: str
    file: str
    span: tuple[int, int]
    group: str
    signature: Signature
    sig_class: str
    state_capture: str  # STATE_CAPTURES
    rust_fn_trait: str  # FN_TRAITS
    ctx_adapter: CtxAdapter
    deps: Deps
    doc: str | None
    hash: str
    #: Verbatim source of the item's body, captured only when indexing with
    #: `--with-source`. Default None keeps every existing index byte-identical and
    #: the file small — a body is always *locatable* from `file`+`span`, this is
    #: about whether it was *captured*. Body translation needs the text (#21);
    #: nothing else reads it. `hash` already covers this text, so staleness
    #: detection vouches for it with no extra machinery.
    source_text: str | None = None
    #: Why this item is entered from outside the index (``name:main``,
    #: ``prefix:Test``, ``file:test``), decided at extraction from the language
    #: profile's ``entry_points``; None when it is not one. Only meaningful on an
    #: index whose ``markers`` include ``entry_points`` (#38). Omitted when None.
    entry_point: str | None = None
    #: Functions used as values (#39), each decided at extraction from the
    #: language profile's ``meta`` block and omitted when empty, so an index
    #: without them is unchanged on disk. Whether a language has the construct
    #: at all is recorded per language in ``ScaIndex.constructs``.
    #: ``decorators``: decorator, annotation or attribute expressions, sigil
    #: stripped (``staticmethod``, ``app.route('/x')``, ``inline``).
    decorators: list[str] = field(default_factory=list)
    #: ``parent``: address of the item this one is nested in (a closure's
    #: enclosing function); None at the top level or inside a class only.
    parent: str | None = None
    #: ``takes_fn``: a parameter is a callable -- typed as one, or called.
    takes_fn: bool = False
    #: ``returns_fn``: a callable is returned -- typed as one, or a function
    #: defined in the body is handed back.
    returns_fn: bool = False

    def to_dict(self) -> dict:
        d = {
            "ordinal": self.ordinal, "address": self.address, "name": self.name,
            "kind": self.kind, "language": self.language, "file": self.file,
            "span": list(self.span), "group": self.group,
            "signature": self.signature.to_dict(), "sig_class": self.sig_class,
            "state_capture": self.state_capture, "rust_fn_trait": self.rust_fn_trait,
            "ctx_adapter": self.ctx_adapter.to_dict(), "deps": self.deps.to_dict(),
            "doc": self.doc, "hash": self.hash,
        }
        # omitted entirely when absent, so indexes built without --with-source are
        # unchanged on disk
        if self.source_text is not None:
            d["source_text"] = self.source_text
        if self.entry_point is not None:
            d["entry_point"] = self.entry_point
        if self.decorators:
            d["decorators"] = self.decorators
        if self.parent is not None:
            d["parent"] = self.parent
        if self.takes_fn:
            d["takes_fn"] = True
        if self.returns_fn:
            d["returns_fn"] = True
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Item:
        ctx = f"item '{d.get('address', d.get('ordinal', '?'))}'"
        span = _req(d, "span", ctx)
        return cls(
            ordinal=int(_req(d, "ordinal", ctx)),
            address=_req(d, "address", ctx),
            name=_req(d, "name", ctx),
            kind=_enum(_req(d, "kind", ctx), ITEM_KINDS, "kind", ctx),
            language=_req(d, "language", ctx),
            file=_req(d, "file", ctx),
            span=(int(span[0]), int(span[1])),
            group=_req(d, "group", ctx),
            signature=Signature.from_dict(_req(d, "signature", ctx), ctx),
            sig_class=_req(d, "sig_class", ctx),
            state_capture=_enum(
                _req(d, "state_capture", ctx), STATE_CAPTURES, "state_capture", ctx
            ),
            rust_fn_trait=_enum(_req(d, "rust_fn_trait", ctx), FN_TRAITS, "rust_fn_trait", ctx),
            ctx_adapter=CtxAdapter.from_dict(_req(d, "ctx_adapter", ctx), ctx),
            deps=Deps.from_dict(d.get("deps", {})),
            doc=d.get("doc"),
            hash=_req(d, "hash", ctx),
            source_text=d.get("source_text"),
            entry_point=d.get("entry_point"),
            decorators=list(d.get("decorators", [])),
            parent=d.get("parent"),
            takes_fn=bool(d.get("takes_fn", False)),
            returns_fn=bool(d.get("returns_fn", False)),
        )


@dataclass
class Group:
    name: str
    kind: str  # GROUP_KINDS
    path: str
    member_ordinals: list[int]
    op_arrays: dict[str, list[int]]
    children: list[Group]

    def to_dict(self) -> dict:
        return {
            "name": self.name, "kind": self.kind, "path": self.path,
            "member_ordinals": self.member_ordinals, "op_arrays": self.op_arrays,
            "children": [c.to_dict() for c in self.children],
        }

    @classmethod
    def from_dict(cls, d: dict) -> Group:
        ctx = f"group '{d.get('path', '?')}'"
        return cls(
            name=_req(d, "name", ctx),
            kind=_enum(_req(d, "kind", ctx), GROUP_KINDS, "group kind", ctx),
            path=_req(d, "path", ctx),
            member_ordinals=list(d.get("member_ordinals", [])),
            op_arrays={k: list(v) for k, v in d.get("op_arrays", {}).items()},
            children=[Group.from_dict(c) for c in d.get("children", [])],
        )

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()


@dataclass
class Pipeline:
    name: str
    stages: list[int]
    checked: bool = False
    # explicit data-flow bindings for direct chains: each edge copies
    # ctx[from_key] -> ctx[to_key] after the stage with ordinal 'after'
    # (a type-approved chain without its edge does not compose — the
    # double→triple defect)
    edges: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"name": self.name, "stages": self.stages, "checked": self.checked,
                "edges": self.edges}

    @classmethod
    def from_dict(cls, d: dict) -> Pipeline:
        ctx = f"pipeline '{d.get('name', '?')}'"
        return cls(
            name=_req(d, "name", ctx),
            stages=[int(s) for s in _req(d, "stages", ctx)],
            checked=bool(d.get("checked", False)),
            edges=list(d.get("edges", [])),
        )


@dataclass
class ScaIndex:
    project_name: str
    root: str
    generated_at: str
    spindlebox_version: str
    items: list[Item]
    groups: list[Group]
    signature_classes: dict[str, dict]
    pipelines: list[Pipeline]
    ctx_schema: dict[str, str]
    retired_ordinals: list[int]
    type_vocabulary: str = TYPE_VOCABULARY
    spi_version: str = SPI_VERSION
    # files the extractor could not parse — serialized so an index can never
    # silently pass as complete while missing code
    parse_errors: list[str] = field(default_factory=list)
    # {relative_path: {hash, mtime, size}} captured at index time, so a caller
    # can tell whether a span is still trustworthy. Empty on indexes built
    # before staleness tracking existed — treated as unverifiable, not clean.
    files: dict[str, dict] = field(default_factory=dict)
    #: Which language-neutral markers extraction wrote into this index:
    #: ``builtin_calls`` (``builtin:`` call edges), ``stdlib_calls``
    #: (``deps.stdlib_calls``) and ``entry_points`` (``item.entry_point``).
    #: Analysis trusts a marker only when it is listed here; an index built
    #: before the markers existed has none, and analysis falls back to its old
    #: heuristics for it (#38). Serialized as ``project.markers``; omitted when empty.
    markers: list[str] = field(default_factory=list)
    #: For each language in the index, the function-as-value constructs its
    #: profile declares present (#39): a subset of ``decorators``, ``parent``,
    #: ``takes_fn``, ``returns_fn``, ``param_calls``, ``table_calls``. An empty
    #: item field means "none here" only for a construct listed for its
    #: language; otherwise the language has no such construct. Serialized as
    #: ``project.constructs``; omitted when empty.
    constructs: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {
            "spi_version": self.spi_version,
            "project": {
                "name": self.project_name, "root": self.root,
                "generated_at": self.generated_at,
                "spindlebox_version": self.spindlebox_version,
            },
            "type_vocabulary": self.type_vocabulary,
            "items": [i.to_dict() for i in self.items],
            "groups": [g.to_dict() for g in self.groups],
            "signature_classes": self.signature_classes,
            "pipelines": [p.to_dict() for p in self.pipelines],
            "ctx_schema": self.ctx_schema,
            "retired_ordinals": self.retired_ordinals,
            "parse_errors": self.parse_errors,
            "files": self.files,
        }
        if self.markers:
            # under `project`, beside the version that wrote them: the top-level
            # key set is read by hand elsewhere and is pinned (test_sidecar)
            d["project"]["markers"] = self.markers
        if self.constructs:
            d["project"]["constructs"] = self.constructs
        return d

    @classmethod
    def from_dict(cls, d: dict) -> ScaIndex:
        project = _req(d, "project", "index")
        # accept legacy pre-rebrand field names (sca_version / findexer_version)
        version = d.get("spi_version", d.get("sca_version"))
        if version is None:
            raise SchemaError("missing required field 'spi_version' in index")
        tool_version = project.get("spindlebox_version", project.get("findexer_version"))
        if tool_version is None:
            raise SchemaError("missing required field 'spindlebox_version' in project")
        return cls(
            spi_version=version,
            project_name=_req(project, "name", "project"),
            root=_req(project, "root", "project"),
            generated_at=_req(project, "generated_at", "project"),
            spindlebox_version=tool_version,
            type_vocabulary=d.get("type_vocabulary", TYPE_VOCABULARY),
            items=[Item.from_dict(i) for i in _req(d, "items", "index")],
            groups=[Group.from_dict(g) for g in d.get("groups", [])],
            signature_classes=dict(d.get("signature_classes", {})),
            pipelines=[Pipeline.from_dict(p) for p in d.get("pipelines", [])],
            ctx_schema=dict(d.get("ctx_schema", {})),
            retired_ordinals=list(d.get("retired_ordinals", [])),
            parse_errors=list(d.get("parse_errors", [])),
            files=dict(d.get("files", {})),
            markers=list(project.get("markers", [])),
            constructs={k: list(v) for k, v in project.get("constructs", {}).items()},
        )

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=1, sort_keys=False) + "\n")
        tmp.replace(path)

    @classmethod
    def load(cls, path: str | Path) -> ScaIndex:
        try:
            data = json.loads(Path(path).read_text())
        except (OSError, json.JSONDecodeError) as e:
            raise SchemaError(f"cannot load index at {path}: {e}") from e
        return cls.from_dict(data)

    def item_by_ordinal(self, ordinal: int) -> Item | None:
        for item in self.items:
            if item.ordinal == ordinal:
                return item
        return None

    def item_by_address(self, address: str) -> Item | None:
        for item in self.items:
            if item.address == address:
                return item
        return None

    def group_by_path(self, path: str) -> Group | None:
        for root in self.groups:
            for g in root.walk():
                if g.path == path:
                    return g
        return None


SpiIndex = ScaIndex  # branded alias — SPI (Serialized Process Index)
