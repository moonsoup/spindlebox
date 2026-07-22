from pathlib import Path

from test_schema import make_index

from spindlebox.extract import build_index
from spindlebox.schema import Pipeline
from spindlebox.validate import validate_index

FIXTURE = Path(__file__).parent / "fixtures" / "miniproj_py"


def test_good_index_passes():
    idx = make_index()
    errors, warnings = validate_index(idx)
    assert errors == []


def test_real_extraction_validates():
    idx = build_index(FIXTURE, project_name="x", langs=["python"])
    errors, _ = validate_index(idx)
    assert errors == []


def test_heterogeneous_op_array_fails():
    idx = make_index()
    idx.groups[0].children[0].op_arrays["sig:str->list<str>"] = [0]
    idx.items[0].sig_class = "sig:i64->i64"
    idx.signature_classes = {"sig:i64->i64": {"params": ["i64"], "returns": "i64", "members": [0]}}
    errors, _ = validate_index(idx)
    assert any("op_array" in e for e in errors)


def test_sig_class_mismatch_fails():
    idx = make_index()
    # claim membership in a class whose shape doesn't match the item's signature
    idx.items[0].sig_class = "sig:i64->i64"
    idx.signature_classes = {"sig:i64->i64": {"params": ["i64"], "returns": "i64", "members": [0]}}
    idx.groups[0].children[0].op_arrays = {"sig:i64->i64": [0]}
    errors, _ = validate_index(idx)
    assert any("signature" in e for e in errors)


def test_ctx_type_conflict_fails():
    idx = make_index()
    idx.ctx_schema["path"] = "i64"  # adapter requires path: str
    errors, _ = validate_index(idx)
    assert any("ctx" in e for e in errors)


def test_pipeline_ctx_chain():
    idx = build_index(FIXTURE, project_name="x", langs=["python"])
    read_lines = idx.item_by_address("util.io.read_lines")
    # a second stage that needs a ctx key ('name') nobody provides
    greet = idx.item_by_address("pure.greet")
    idx.pipelines = [Pipeline(name="bad", stages=[read_lines.ordinal, greet.ordinal])]
    errors, _ = validate_index(idx)
    assert any("pipeline" in e for e in errors)
    # direct chain: double → triple (i64 → i64)
    d = idx.item_by_address("app.double")
    t = idx.item_by_address("app.triple")
    idx.pipelines = [Pipeline(name="ok", stages=[d.ordinal, t.ordinal])]
    errors, _ = validate_index(idx)
    assert errors == []


def test_duplicate_ordinal_fails():
    idx = make_index()
    other = make_index().items[0]
    other.address = "src.mod.g"
    idx.items.append(other)  # same ordinal 0
    errors, _ = validate_index(idx)
    assert any("ordinal" in e for e in errors)


def test_strict_flags_any():
    idx = make_index()
    idx.items[0].signature.params[0].norm_type = "any"
    idx.items[0].sig_class = "sig:any->list<str>"
    idx.signature_classes = {
        "sig:any->list<str>": {"params": ["any"], "returns": "list<str>", "members": [0]}
    }
    idx.groups[0].children[0].op_arrays = {"sig:any->list<str>": [0]}
    errors, warnings = validate_index(idx)
    assert errors == [] and any("any" in w for w in warnings)
    errors, _ = validate_index(idx, strict=True)
    assert any("any" in e for e in errors)
