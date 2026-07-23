from pathlib import Path

import pytest

from spindlebox.extract import build_index

FIXTURE = Path(__file__).parent / "fixtures" / "miniproj_go"


@pytest.fixture(scope="module")
def idx():
    return build_index(FIXTURE, project_name="miniproj_go", langs=["go"])


def by_addr(idx, address):
    item = idx.item_by_address(address)
    assert item is not None, f"no item at {address}; have {[i.address for i in idx.items]}"
    return item


def test_typed_function_cross_language_class(idx):
    item = by_addr(idx, "main.ReadLines")
    assert item.sig_class == "sig:str->list<str>"
    assert item.doc == "ReadLines reads lines from a file."


def test_multi_return_result(idx):
    item = by_addr(idx, "main.ReadAll")
    assert item.signature.returns_norm == "result<list<str>,error>"


def test_env_var(idx):
    assert by_addr(idx, "main.Home").deps.env_vars == ["APP_HOME"]


def test_mutating_closure(idx):
    closures = [i for i in idx.items
                if i.kind == "closure" and "MakeCounter" in i.address]
    assert closures, "no closure extracted inside MakeCounter"
    assert closures[0].state_capture == "mutates_captured"


def test_method_receiver(idx):
    item = by_addr(idx, "main.Reader.Read")
    assert item.kind == "method"
    assert item.signature.params[0].kind == "receiver"
    assert item.sig_class == "sig:->list<str>"
    assert "main.ReadLines" in item.deps.calls


def test_external_package(idx):
    item = by_addr(idx, "main.ReadLines")
    assert "github.com/pkg/errors" in item.deps.external_packages
    assert not any(p in ("os", "strings") for p in item.deps.external_packages)
