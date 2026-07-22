from pathlib import Path

import pytest

from spindlebox.dispatch import DispatchError, call_item
from spindlebox.extract import build_index

FIXTURE = Path(__file__).parent / "fixtures" / "miniproj_py"


@pytest.fixture(scope="module")
def idx():
    return build_index(FIXTURE, project_name="miniproj_py", langs=["python"])


def test_call_by_address(idx):
    out = call_item(idx, FIXTURE, "pure.add", {"a": 2, "b": 3})
    assert out["add_result"] == 5
    assert out["a"] == 2  # original ctx preserved


def test_call_by_ordinal(idx):
    item = idx.item_by_address("pure.add")
    out = call_item(idx, FIXTURE, str(item.ordinal), {"a": 1, "b": 1})
    assert out["add_result"] == 2


def test_default_used_when_key_absent(idx):
    out = call_item(idx, FIXTURE, "pure.greet", {"name": "isme"})
    assert out["greet_result"] == "hello isme!"


def test_missing_required_key(idx):
    with pytest.raises(DispatchError, match="missing"):
        call_item(idx, FIXTURE, "pure.add", {"a": 2})


def test_non_function_rejected(idx):
    with pytest.raises(DispatchError, match="only module-level"):
        call_item(idx, FIXTURE, "util.io.Reader.read", {})


def test_unknown_address(idx):
    with pytest.raises(DispatchError, match="no item"):
        call_item(idx, FIXTURE, "nope.nothing", {})
