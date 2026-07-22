"""Java is extracted purely from its declarative profile — no java_lang.py exists."""

from pathlib import Path

import pytest

from spindlebox.extract import build_index

FIXTURE = Path(__file__).parent / "fixtures" / "miniproj_java"


@pytest.fixture(scope="module")
def idx():
    return build_index(FIXTURE, project_name="miniproj_java", langs=["java"])


def by_addr(idx, address):
    item = idx.item_by_address(address)
    assert item is not None, f"no item at {address}; have {[i.address for i in idx.items]}"
    return item


def test_no_handwritten_extractor_module():
    import spindlebox.extract as pkg
    assert not (Path(pkg.__file__).parent / "java_lang.py").exists()


def test_typed_function_cross_language_class(idx):
    item = by_addr(idx, "TextKit.TextKit.readLines")
    assert item.sig_class == "sig:str->list<str>"  # same class as Go/Python readLines
    assert item.doc == "readLines reads lines from a file."


def test_constructor_is_method(idx):
    ctor = [i for i in idx.items if i.name == "TextKit" and i.kind == "method"]
    assert ctor and ctor[0].state_capture == "mutates_instance"


def test_varargs_and_instance_mutation(idx):
    item = by_addr(idx, "TextKit.TextKit.bump")
    assert item.state_capture == "mutates_instance"
    variadic = [p for p in item.signature.params if p.kind == "variadic"]
    assert variadic and variadic[0].norm_type == "list<i64>"


def test_lambda_reads_captured_local(idx):
    lambdas = [i for i in idx.items if i.kind == "lambda"]
    assert lambdas, "no lambdas extracted"
    assert lambdas[0].state_capture == "reads_captured"


def test_env_var(idx):
    assert by_addr(idx, "TextKit.TextKit.home").deps.env_vars == ["APP_HOME"]


def test_option_map_return(idx):
    item = by_addr(idx, "TextKit.TextKit.lookup")
    assert item.signature.returns_norm == "option<map<str,i64>>"


def test_call_resolution(idx):
    item = by_addr(idx, "TextKit.TextKit.lookup")
    assert "TextKit.TextKit.helperThing" in item.deps.calls


def test_interface_method(idx):
    item = by_addr(idx, "Shape.Shape.area")
    assert item.kind == "method"
    assert item.signature.returns_norm == "f64"
