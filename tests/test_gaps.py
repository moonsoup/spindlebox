from pathlib import Path

import pytest

from spindlebox.extract import build_index
from spindlebox.gaps import find_gaps

FIXTURE = Path(__file__).parent / "fixtures" / "miniproj_gaps"


@pytest.fixture(scope="module")
def gaps():
    idx = build_index(FIXTURE, project_name="gaps", langs=["python"])
    return find_gaps(idx)


def by_kind(gaps, kind):
    return {g["address"] for g in gaps if g["kind"] == kind}


def test_dead_item_detected(gaps):
    dead = by_kind(gaps, "dead_item")
    assert "pipeline.island" in dead


def test_live_items_not_dead(gaps):
    dead = by_kind(gaps, "dead_item")
    assert "pipeline.main" not in dead          # entrypoint
    assert "pipeline.used_helper" not in dead    # called by main
    assert "pipeline.load" not in dead           # provides load_result (ctx edge)
    assert "pipeline.clean" not in dead          # ctx chain member
    assert "pipeline.summarize" not in dead      # consumes clean_result


def test_unprovided_ctx_key(gaps):
    keys = {g["detail"] for g in gaps if g["kind"] == "unprovided_ctx_key"}
    assert "phantom_result" in keys
    # plain entry inputs (no _result convention) are not high-severity gaps
    high = {g["detail"] for g in gaps
            if g["kind"] == "unprovided_ctx_key" and g["severity"] == "high"}
    assert "phantom_result" in high


def test_unresolvable_call(gaps):
    unresolved = {g["detail"] for g in gaps if g["kind"] == "unresolvable_call"}
    assert "does_not_exist_anywhere" in unresolved


def test_near_duplicate_cluster(gaps):
    clusters = [set(g["members"]) for g in gaps if g["kind"] == "near_duplicate"]
    assert any({"pipeline.compute_alpha", "pipeline.compute_beta"} <= c for c in clusters)


def test_gaps_are_serializable(gaps):
    import json
    json.dumps(gaps)  # every gap record must be plain JSON
    for g in gaps:
        assert {"kind", "severity"} <= set(g)
