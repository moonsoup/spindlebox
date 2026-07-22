from pathlib import Path

import pytest

from spindlebox.extract import build_index
from spindlebox.validate import validate_index

FIXTURE = Path(__file__).parent / "fixtures" / "miniproj_mixed"


@pytest.fixture(scope="module")
def idx():
    return build_index(FIXTURE, project_name="miniproj_mixed")


def test_all_languages_extracted(idx):
    langs = {i.language for i in idx.items}
    assert {"python", "typescript", "go", "rust", "bash"} <= langs


def test_cross_language_signature_class(idx):
    """The core SCA claim: same shape → same class, regardless of language."""
    sc = idx.signature_classes.get("sig:str->list<str>")
    assert sc is not None
    members = [idx.item_by_ordinal(o) for o in sc["members"]]
    langs = {m.language for m in members}
    assert {"python", "typescript", "go", "rust"} <= langs


def test_mixed_index_validates(idx):
    errors, _ = validate_index(idx)
    assert errors == []
