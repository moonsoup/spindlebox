from spindlebox.ctxnorm import apply_ctx_normalization
from spindlebox.schema import CtxAdapter, Deps, Item, Param, Signature


def make_item(ordinal, name, group, params, ret):
    return Item(
        ordinal=ordinal,
        address=f"{group}.{name}",
        name=name,
        kind="function",
        language="python",
        file=group.replace(".", "/") + ".py",
        span=(1, 2),
        group=group,
        signature=Signature(
            params=[
                Param(name=n, raw_type=None, norm_type=t, default=None, kind="positional")
                for n, t in params
            ],
            returns_raw=None,
            returns_norm=ret,
        ),
        sig_class="sig:x",
        state_capture="pure",
        rust_fn_trait="fn",
        ctx_adapter=CtxAdapter(requires={}, provides={}, param_map={}, return_key=None),
        deps=Deps(),
        doc=None,
        hash="sha256:0",
    )


def test_adapter_built():
    a = make_item(0, "read_lines", "mod", [("path", "str")], "list<str>")
    schema = apply_ctx_normalization([a])
    assert a.ctx_adapter.requires == {"path": "str"}
    assert a.ctx_adapter.param_map == {"path": "ctx.path"}
    assert a.ctx_adapter.return_key == "read_lines_result"
    assert a.ctx_adapter.provides == {"read_lines_result": "list<str>"}
    assert a.deps.ctx_keys_required == ["path"]
    assert schema == {"path": "str", "read_lines_result": "list<str>"}


def test_same_key_same_type_shared():
    a = make_item(0, "f", "m1", [("path", "str")], "unit")
    b = make_item(1, "g", "m2", [("path", "str")], "unit")
    schema = apply_ctx_normalization([a, b])
    assert a.ctx_adapter.requires == {"path": "str"}
    assert b.ctx_adapter.requires == {"path": "str"}
    assert schema["path"] == "str"


def test_key_collision_renamed():
    a = make_item(0, "f", "m1", [("count", "i64")], "unit")
    b = make_item(1, "g", "m2", [("count", "str")], "unit")
    schema = apply_ctx_normalization([a, b])
    assert a.ctx_adapter.requires == {"count": "i64"}
    # b's conflicting key gets renamed, mapping preserved
    (renamed,) = b.ctx_adapter.requires.keys()
    assert renamed != "count" and "count" in renamed
    assert b.ctx_adapter.param_map == {"count": f"ctx.{renamed}"}
    assert schema["count"] == "i64" and schema[renamed] == "str"


def test_return_key_collision_renamed():
    a = make_item(0, "f", "m1", [], "i64")
    b = make_item(1, "f", "m2", [], "str")  # same name, different return type
    schema = apply_ctx_normalization([a, b])
    assert a.ctx_adapter.return_key == "f_result"
    assert b.ctx_adapter.return_key != "f_result"
    assert schema[a.ctx_adapter.return_key] == "i64"
    assert schema[b.ctx_adapter.return_key] == "str"


def test_unit_return_no_key():
    a = make_item(0, "f", "m", [], "unit")
    apply_ctx_normalization([a])
    assert a.ctx_adapter.return_key is None
    assert a.ctx_adapter.provides == {}
