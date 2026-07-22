from pathlib import Path

import pytest

from spindlebox.extract import build_index
from spindlebox.workflows import mine_workflows

FIXTURE = Path(__file__).parent / "fixtures" / "miniproj_gaps"


@pytest.fixture(scope="module")
def flows():
    idx = build_index(FIXTURE, project_name="gaps", langs=["python"])
    return mine_workflows(idx, min_confidence=0.5)


def test_ctx_chain_workflow_found(flows):
    """The planted load -> clean -> summarize ctx chain must be mined."""
    chains = [f["addresses"] for f in flows]
    assert any(
        c[:3] == ["pipeline.load", "pipeline.clean", "pipeline.summarize"]
        or {"pipeline.load", "pipeline.clean", "pipeline.summarize"} <= set(c)
        for c in chains
    )


def test_confidence_and_threshold():
    idx = build_index(FIXTURE, project_name="gaps", langs=["python"])
    low = mine_workflows(idx, min_confidence=0.1)
    high = mine_workflows(idx, min_confidence=0.95)
    assert len(low) >= len(high)
    for f in high:
        assert f["confidence"] >= 0.95


def test_pipeline_define_compatible(flows):
    """Output must be directly usable by `pipeline define` (ordered addresses)."""
    for f in flows:
        assert isinstance(f["addresses"], list) and len(f["addresses"]) >= 2
        assert "ordinals" in f and len(f["ordinals"]) == len(f["addresses"])
        assert 0.0 <= f["confidence"] <= 1.0


def test_call_edge_workflow(flows):
    """main -> used_helper is a call edge; should appear as a (short) workflow."""
    assert any({"pipeline.main", "pipeline.used_helper"} <= set(f["addresses"])
               for f in flows)
