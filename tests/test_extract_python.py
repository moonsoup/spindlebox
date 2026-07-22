from pathlib import Path

import pytest

from spindlebox.extract import build_index

FIXTURE = Path(__file__).parent / "fixtures" / "miniproj_py"


@pytest.fixture(scope="module")
def idx():
    return build_index(FIXTURE, project_name="miniproj_py", langs=["python"])


def by_addr(idx, address):
    item = idx.item_by_address(address)
    assert item is not None, f"no item at {address}; have {[i.address for i in idx.items]}"
    return item


def test_free_function_typed(idx):
    item = by_addr(idx, "util.io.read_lines")
    assert item.kind == "function"
    assert item.sig_class == "sig:str->list<str>"
    assert item.state_capture == "pure"
    assert item.rust_fn_trait == "fn"
    assert item.doc == "Read lines from a file."


def test_free_function_untyped(idx):
    item = by_addr(idx, "util.io.parse_blob")
    assert item.sig_class == "sig:any->any"


def test_method_receiver_excluded_from_sig(idx):
    item = by_addr(idx, "util.io.Reader.read")
    assert item.kind == "method"
    assert item.signature.params[0].kind == "receiver"
    assert item.sig_class == "sig:->list<str>"
    assert item.state_capture == "mutates_instance"
    assert item.rust_fn_trait == "FnMut"


def test_reading_method(idx):
    item = by_addr(idx, "util.io.Reader.peek")
    assert item.state_capture == "reads_instance"
    assert item.rust_fn_trait == "Fn"


def test_mutating_closure(idx):
    item = by_addr(idx, "app.make_counter.bump")
    assert item.kind == "closure"
    assert item.state_capture == "mutates_captured"
    assert item.rust_fn_trait == "FnMut"


def test_reading_closure(idx):
    item = by_addr(idx, "app.make_reader.read")
    assert item.state_capture == "reads_captured"
    assert item.rust_fn_trait == "Fn"


def test_env_var_detected(idx):
    item = by_addr(idx, "app.home")
    assert item.deps.env_vars == ["FINDEXER_HOME"]


def test_intra_index_call_resolved(idx):
    item = by_addr(idx, "util.io.Reader.read")
    assert "util.io.read_lines" in item.deps.calls
    # cross-module resolution via unique global name
    closure = by_addr(idx, "app.make_reader.read")
    assert "util.io.read_lines" in closure.deps.calls


def test_external_package(idx):
    item = by_addr(idx, "util.io.read_lines")
    assert "requests" in item.deps.external_packages
    assert "json" not in item.deps.external_packages  # stdlib
    assert "util" not in item.deps.external_packages  # project-local


def test_op_arrays_partitioned_by_signature(idx):
    app_group = idx.group_by_path("app")
    assert app_group is not None
    d = by_addr(idx, "app.double")
    t = by_addr(idx, "app.triple")
    assert d.sig_class == t.sig_class == "sig:i64->i64"
    members = app_group.op_arrays[d.sig_class]
    assert d.ordinal in members and t.ordinal in members
    # every op array is signature-homogeneous
    for sig, ordinals in app_group.op_arrays.items():
        for o in ordinals:
            assert idx.item_by_ordinal(o).sig_class == sig


def test_class_group_exists(idx):
    g = idx.group_by_path("util.io.Reader")
    assert g is not None and g.kind == "class"
    assert by_addr(idx, "util.io.Reader.read").ordinal in g.member_ordinals


def test_ctx_adapter(idx):
    item = by_addr(idx, "util.io.read_lines")
    ad = item.ctx_adapter
    assert ad.requires == {"path": "str"}
    assert ad.return_key == "read_lines_result"
    assert ad.provides == {"read_lines_result": "list<str>"}
    assert idx.ctx_schema["path"] == "str"


def test_ordinals_deterministic(idx):
    idx2 = build_index(FIXTURE, project_name="miniproj_py", langs=["python"])
    assert [(i.ordinal, i.address) for i in idx.items] == [
        (i.ordinal, i.address) for i in idx2.items
    ]


def test_signature_classes_members(idx):
    sc = idx.signature_classes["sig:i64->i64"]
    d = by_addr(idx, "app.double")
    assert d.ordinal in sc["members"]
