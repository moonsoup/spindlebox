"""Root-cause tests for the gaps/workflows noise recorded in issue #17 (audit 2026-08-03).

Intended path: tests/test_analytics_accuracy.py

Issue #17 records the symptom — "208 of 426 gaps are false positives; all 171 workflow
candidates return identical confidence" — and defers it. These tests pin the *causes*
found by reading the source, so a fix can be verified rather than eyeballed.

The headline finding is ANL-03: a single defect in `depmap.resolve_calls` explains BOTH
halves of #17. Name ambiguity silently converts an intra-project call into an
`external:` edge, which (a) removes the callee's only caller, so `gaps` reports it dead,
and (b) zeroes the call term in the workflow edge score, so the edge is dropped.

Like tests/test_conversion_fidelity.py these are characterization tests: green CONFIRMS
the audit's static reading. They were written without executing anything, so a failure
means the audit misread the code — a useful result, and the reason they exist.

Findings: ANL-01 (dead code, benign), ANL-02 (threshold), ANL-03 (root cause).
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from spindlebox.depmap import resolve_calls
from spindlebox.extract import build_index
from spindlebox.gaps import find_gaps
from spindlebox.workflows import W_CALL, W_CTX, W_GROUP, mine_workflows

FIXTURE = Path(__file__).parent / "fixtures" / "miniproj_gaps"


@pytest.fixture(scope="module")
def idx():
    return build_index(FIXTURE, project_name="gaps", langs=["python"])


# ------------------------------- ANL-03: ambiguous call names become external: edges


def test_ambiguous_name_is_kept_distinct_from_external():
    """THE root cause of #17, both halves — now fixed.

    `depmap.resolve_calls` resolves a called name by: (1) unique in the caller's own
    module, (2) unique index-wide, (3) `ambiguous:` if the name IS defined here but
    more than once, (4) `external:` if it is not in the index at all.

    Before the fix, cases 3 and 4 both produced `external:`, discarding the edge.
    Reused names are the COMMON ones — run, main, get, parse, close, to_dict — so the
    loss was concentrated exactly where it hurt, and grew with codebase size.
    """
    ambiguous = {"run": ["a.mod.run", "b.mod.run"]}
    assert resolve_calls(["run"], "c.other", ambiguous) == ["ambiguous:run"]


def test_name_absent_from_the_index_is_still_external():
    """The `external:` contract is unchanged for genuine third-party calls — builtins,
    stdlib, typos. Several consumers key on that prefix, and docs/guide/querying.md:296
    is a docs-enforced example showing `external:open, external:splitlines`."""
    assert resolve_calls(["open"], "util.io", {}) == ["external:open"]
    assert resolve_calls(["json.loads"], "util.io", {"read": ["util.io.Reader.read"]}) == [
        "external:json.loads"
    ]


def test_unique_and_same_module_names_do_resolve():
    """The two paths that work, pinned so a fix to ANL-03 cannot regress them."""
    assert resolve_calls(["parse"], "c.other", {"parse": ["x.parse"]}) == ["x.parse"]
    # same-module wins even when the name is globally ambiguous
    assert resolve_calls(["run"], "a.mod", {"run": ["a.mod.run", "b.mod.run"]}) == ["a.mod.run"]


def test_method_style_calls_use_only_the_last_segment():
    """`obj.method()` is resolved on "method" alone (depmap.py:107), so every class
    with a `run`/`get`/`close` method collides with every other one. This is what makes
    ambiguity the normal case rather than the exception in real code — and why the edge
    must be kept rather than dropped."""
    ambiguous = {"close": ["io.Reader.close", "net.Socket.close"]}
    assert resolve_calls(["self.close"], "app.thing", ambiguous) == ["ambiguous:self.close"]


def test_consequence_a_ambiguous_calls_credit_every_candidate():
    """`gaps._reverse_call_map` credits an ambiguous call to every same-named item, so a
    live-but-commonly-named function is no longer reported dead.

    Under-crediting reports live code as dead, which is what made `gaps` unusable (#17);
    over-crediting merely risks missing a genuinely dead item. The conservative direction
    is the right one.
    """
    from spindlebox.gaps import _reverse_call_map

    items = build_index(FIXTURE, project_name="gaps", langs=["python"]).items
    callers = _reverse_call_map(items)
    for item in items:
        for callee in item.deps.calls:
            if callee.startswith("ambiguous:"):
                name = callee[len("ambiguous:"):].rsplit(".", 1)[-1]
                for other in items:
                    if other.name == name and other.address != item.address:
                        assert item.address in callers.get(other.address, set())


def test_consequence_b_workflows_zero_the_call_term():
    """workflows.py:30 tests `b.address in a.deps.calls`. An `external:` entry never
    equals an item address, so `calls` is 0.0 and the edge can score at most
    W_CTX + W_GROUP = 0.5 — below the 0.6 default, so it is dropped entirely.

    Ambiguously-named calls are therefore invisible to workflow mining too, which is why
    the surviving edges are so uniform (see ANL-02).
    """
    assert round(W_CTX + W_GROUP, 4) < inspect.signature(
        mine_workflows).parameters["min_confidence"].default


# --------------------------------------- ANL-02: the default threshold pins confidence


def test_default_threshold_exactly_equals_a_plain_call_edge_score():
    """Why every mined workflow reports the same confidence.

    Edge score (workflows.py:35) is 0.5*calls + 0.4*ctx_coverage + 0.1*same_subtree.
    The commonest surviving edge — A calls B, both in one group, no shared ctx keys —
    scores W_CALL + W_GROUP = 0.6, EXACTLY the default min_confidence. It is admitted at
    precisely the cutoff. Flow confidence is `min(confs)` (:72), so one such edge
    anywhere on a path pins the whole candidate to 0.60.

    #17's "all 171 candidates return identical confidence" is therefore structural.
    docs/guide/analysis.md:80-81 shows it in the project's own output: two candidates,
    both [conf 0.60].
    """
    default = inspect.signature(mine_workflows).parameters["min_confidence"].default
    assert default == 0.6

    # round() mirrors _edge_confidence, which rounds to 4dp; 0.5 + 0.1 is
    # 0.6000000000000001 in binary floating point.
    plain_call_in_group = round(W_CALL * 1.0 + W_CTX * 0.0 + W_GROUP * 1.0, 4)
    assert plain_call_in_group == default


def test_a_call_edge_across_groups_falls_below_the_default():
    """The mirror image: the same call edge in a different group scores 0.5 and is
    dropped. The default threshold is a near-binary filter on `same_subtree`, not a
    confidence gradient — which is why surviving scores do not spread."""
    default = inspect.signature(mine_workflows).parameters["min_confidence"].default
    assert round(W_CALL * 1.0 + W_GROUP * 0.0, 4) < default


def test_existing_workflow_tests_avoid_the_default_threshold():
    """Why the suite never caught ANL-02: tests/test_workflows.py:14 builds its fixture
    with min_confidence=0.5, and test_confidence_and_threshold asserts only monotonicity
    (len(low) >= len(high)) — never that confidences DIFFER."""
    src = (Path(__file__).parent / "test_workflows.py").read_text()
    assert "min_confidence=0.5" in src
    assert "min_confidence=0.6" not in src


def test_mined_confidence_spread_at_default_threshold(idx):
    """The observable symptom, recorded rather than asserted — the fixture is small, so
    this prints the spread instead of hard-failing on it. On a real project #17 measured
    exactly one distinct value across 171 candidates."""
    flows = mine_workflows(idx)  # default threshold
    spread = sorted({f["confidence"] for f in flows})
    print(f"\ndistinct confidences at default threshold: {spread} over {len(flows)} candidates")
    for f in flows:
        assert 0.0 <= f["confidence"] <= 1.0


# --------------------------------- ANL-01: dead code in gaps.py — benign, NOT a bug


def test_ctx_schema_intersection_in_gaps_is_dead_code(idx):
    """gaps.py:68-71 computes

        provided  = set(idx.ctx_schema) & {all provides}
        provided |= {all provides}

    Since (ctx_schema n P) is a subset of P, `provided == P` for every possible input.
    The first statement cannot affect the result: it is dead code.

    **It is dead code, not a defect — do not "fix" it by changing `&` to `|`.**
    validate.py:113-115 makes every ctx key mandatory in ctx_schema, so ctx_schema
    contains required-but-unprovided keys too. Unioning it in would mark every key as
    provided and suppress the gap check entirely. The current effective behaviour
    (provided == the set actually provided) is the correct semantics.

    Recorded so the confusing line is either deleted or commented deliberately. The real
    false-positive source is ANL-03 above.
    """
    baseline = {g["detail"] for g in find_gaps(idx) if g["kind"] == "unprovided_ctx_key"}
    assert "phantom_result" in baseline, "fixture precondition: phantom_result is unprovided"

    idx.ctx_schema["phantom_result"] = "any"
    after = {g["detail"] for g in find_gaps(idx) if g["kind"] == "unprovided_ctx_key"}

    assert baseline == after, "declaring a key in ctx_schema must change nothing"
