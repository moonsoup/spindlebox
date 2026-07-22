import pytest

from findexer.schema import (
    CtxAdapter,
    Deps,
    Group,
    Item,
    Param,
    ScaIndex,
    SchemaError,
    Signature,
)


def make_item(ordinal=0, address="src.mod.f", sig_class="sig:str->list<str>"):
    return Item(
        ordinal=ordinal,
        address=address,
        name=address.rsplit(".", 1)[-1],
        kind="function",
        language="python",
        file="src/mod.py",
        span=(1, 5),
        group="src.mod",
        signature=Signature(
            params=[Param(name="path", raw_type="str", norm_type="str", default=None, kind="positional")],
            returns_raw="list[str]",
            returns_norm="list<str>",
            is_async=False,
        ),
        sig_class=sig_class,
        state_capture="pure",
        rust_fn_trait="fn",
        ctx_adapter=CtxAdapter(
            requires={"path": "str"},
            provides={"f_result": "list<str>"},
            param_map={"path": "ctx.path"},
            return_key="f_result",
        ),
        deps=Deps(calls=[], imports=[], external_packages=[], env_vars=[], ctx_keys_required=["path"]),
        doc="Read lines.",
        hash="sha256:x",
    )


def make_index():
    item = make_item()
    return ScaIndex(
        project_name="demo",
        root="/tmp/demo",
        generated_at="2026-07-21T00:00:00",
        findexer_version="0.1.0",
        items=[item],
        groups=[
            Group(
                name="src", kind="package", path="src", member_ordinals=[],
                op_arrays={},
                children=[
                    Group(name="mod", kind="module", path="src.mod",
                          member_ordinals=[0],
                          op_arrays={"sig:str->list<str>": [0]}, children=[])
                ],
            )
        ],
        signature_classes={"sig:str->list<str>": {"params": ["str"], "returns": "list<str>", "members": [0]}},
        pipelines=[],
        ctx_schema={"path": "str", "f_result": "list<str>"},
        retired_ordinals=[],
    )


def test_round_trip(tmp_path):
    idx = make_index()
    p = tmp_path / "index.json"
    idx.save(p)
    loaded = ScaIndex.load(p)
    assert loaded.to_dict() == idx.to_dict()
    assert loaded.items[0].signature.params[0].norm_type == "str"
    assert loaded.groups[0].children[0].op_arrays == {"sig:str->list<str>": [0]}


def test_lookup_helpers():
    idx = make_index()
    assert idx.item_by_ordinal(0).name == "f"
    assert idx.item_by_address("src.mod.f").ordinal == 0
    assert idx.item_by_ordinal(99) is None


def test_missing_field_rejected():
    idx = make_index()
    d = idx.to_dict()
    del d["items"][0]["sig_class"]
    with pytest.raises(SchemaError):
        ScaIndex.from_dict(d)


def test_bad_enum_rejected():
    idx = make_index()
    d = idx.to_dict()
    d["items"][0]["state_capture"] = "haunted"
    with pytest.raises(SchemaError):
        ScaIndex.from_dict(d)
