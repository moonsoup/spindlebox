from pathlib import Path

import pytest

from spindlebox.extract import build_index

FIXTURE = Path(__file__).parent / "fixtures" / "miniproj_rust"


@pytest.fixture(scope="module")
def idx():
    return build_index(FIXTURE, project_name="miniproj_rust", langs=["rust"])


def by_addr(idx, address):
    item = idx.item_by_address(address)
    assert item is not None, f"no item at {address}; have {[i.address for i in idx.items]}"
    return item


def test_typed_function_cross_language_class(idx):
    item = by_addr(idx, "src.lib.read_lines")
    assert item.sig_class == "sig:str->list<str>"
    assert item.doc == "Read lines from a file."


def test_env_var(idx):
    assert by_addr(idx, "src.lib.home").deps.env_vars == ["APP_HOME"]


def test_mut_self_method(idx):
    item = by_addr(idx, "src.lib.Reader.read")
    assert item.kind == "method"
    assert item.state_capture == "mutates_instance"
    assert item.rust_fn_trait == "FnMut"
    assert "src.lib.read_lines" in item.deps.calls


def test_ref_self_method(idx):
    item = by_addr(idx, "src.lib.Reader.peek")
    assert item.state_capture == "reads_instance"
    assert item.rust_fn_trait == "Fn"


def test_move_closure_consumes(idx):
    closures = [i for i in idx.items
                if i.kind == "closure" and "make_adder" in i.address]
    assert closures, "no closure extracted inside make_adder"
    assert closures[0].state_capture == "consumes"
    assert closures[0].rust_fn_trait == "FnOnce"


def test_consuming_self_method(idx):
    item = by_addr(idx, "src.extra.inner.Token.consume")
    assert item.state_capture == "consumes"
    assert item.rust_fn_trait == "FnOnce"


def test_nested_module_function(idx):
    item = by_addr(idx, "src.extra.inner.deeper.double")
    assert item.sig_class == "sig:i64->i64"


def test_nested_fn_is_pure_closure(idx):
    item = by_addr(idx, "src.extra.outer.helper")
    assert item.kind == "closure"
    assert item.state_capture == "pure"


def test_external_package(idx):
    item = by_addr(idx, "src.lib.parse_blob")
    assert "serde_json" in item.deps.external_packages
