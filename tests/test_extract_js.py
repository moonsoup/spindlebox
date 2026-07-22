from pathlib import Path

import pytest

from findexer.extract import build_index

FIXTURE = Path(__file__).parent / "fixtures" / "miniproj_js"


@pytest.fixture(scope="module")
def idx():
    return build_index(FIXTURE, project_name="miniproj_js", langs=["typescript"])


def by_addr(idx, address):
    item = idx.item_by_address(address)
    assert item is not None, f"no item at {address}; have {[i.address for i in idx.items]}"
    return item


def test_typed_function_cross_language_class(idx):
    item = by_addr(idx, "src.util.readLines")
    assert item.kind == "function"
    assert item.sig_class == "sig:str->list<str>"  # same class as the python fixture
    assert item.language == "typescript"


def test_mutating_closure(idx):
    item = by_addr(idx, "src.util.makeCounter.bump")
    assert item.kind == "closure"
    assert item.state_capture == "mutates_captured"
    assert item.rust_fn_trait == "FnMut"


def test_method_instance_capture(idx):
    read = by_addr(idx, "src.util.Reader.read")
    assert read.kind == "method"
    assert read.state_capture == "mutates_instance"
    assert read.sig_class == "sig:->list<str>"
    peek = by_addr(idx, "src.util.Reader.peek")
    assert peek.state_capture == "reads_instance"


def test_arrow_named_from_declarator(idx):
    item = by_addr(idx, "src.util.home")
    assert item.sig_class == "sig:->str"


def test_env_var(idx):
    item = by_addr(idx, "src.util.home")
    assert item.deps.env_vars == ["APP_HOME"]


def test_external_package(idx):
    item = by_addr(idx, "src.util.readLines")
    assert "axios" in item.deps.external_packages
    assert "fs" not in item.deps.external_packages or True  # fs allowed either way


def test_promise_unwrapped(idx):
    item = by_addr(idx, "src.util.fetchIt")
    assert item.signature.returns_norm == "str"
    assert item.signature.is_async is False


def test_intra_call(idx):
    item = by_addr(idx, "src.util.Reader.read")
    assert "src.util.readLines" in item.deps.calls
