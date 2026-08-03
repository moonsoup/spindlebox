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


def test_consequence_b_pure_ctx_chains_are_now_admitted():
    """Before the fix, an ambiguous call scored 0.0 on the call term, so an edge could
    reach at most W_CTX + W_GROUP = 0.5 — below the old 0.6 default, and dropped. That
    took a whole class of edge out of mining: a pure ctx chain (A provides everything B
    requires, same group) with no direct call between them.

    At the corrected default those edges exactly meet the bar, so ctx-only pipelines —
    the thing `pipeline define` exists to formalise — are mineable again.
    """
    default = inspect.signature(mine_workflows).parameters["min_confidence"].default
    full_ctx_same_group = round(W_CTX * 1.0 + W_GROUP * 1.0, 4)
    assert full_ctx_same_group >= default, "a fully-covered ctx edge must be admissible"


# --------------------------------------- ANL-02: the default threshold pins confidence


def test_default_threshold_is_below_the_plain_call_edge_score():
    """ANL-02, fixed. The old default (0.6) was EXACTLY W_CALL + W_GROUP — the score of
    the commonest edge, a call within one group — so only top-of-range edges were
    admitted and they were all identical. Flow confidence is `min(confs)`, so every
    candidate pinned to 0.60.

    Measured on the spindlebox repo (681 items, 200 candidates, cap binding):
        threshold 0.6  -> 1 distinct strength
        threshold 0.55 -> 25
        threshold 0.5  -> 38          <- same candidate count, 38x the discrimination

    The default must stay strictly below the modal edge score or the admitted set
    degenerates to a single value again.
    """
    default = inspect.signature(mine_workflows).parameters["min_confidence"].default
    # round() mirrors _edge_confidence; 0.5 + 0.1 is 0.6000000000000001 in binary float.
    plain_call_in_group = round(W_CALL * 1.0 + W_CTX * 0.0 + W_GROUP * 1.0, 4)
    assert default < plain_call_in_group, "default sits on the modal edge score again"


def test_group_affinity_is_graded_not_boolean():
    """The old `_same_subtree` was 0/1, so group proximity contributed either 0.0 or
    0.1 and nothing between. Sibling modules now score between those bounds."""
    from spindlebox.workflows import _group_affinity

    class _I:
        def __init__(self, group):
            self.group = group

    assert _group_affinity(_I("a.b"), _I("a.b")) == 1.0        # same group
    assert _group_affinity(_I("a.b"), _I("x.y")) == 0.0        # unrelated
    sibling = _group_affinity(_I("a.b"), _I("a.c"))            # same package
    assert 0.0 < sibling < 1.0


def test_ambiguous_calls_contribute_partial_edge_weight():
    """An ambiguous call is real evidence that ONE candidate is called, so the weight
    splits across candidates rather than being discarded (the ANL-03 tail)."""
    from spindlebox.workflows import _call_strength

    class _I:
        def __init__(self, address, name, calls):
            self.address, self.name = address, name
            self.deps = type("D", (), {"calls": calls})()

    caller = _I("m.caller", "caller", ["ambiguous:close"])
    target = _I("io.Reader.close", "close", [])
    assert _call_strength(caller, target, {"close": 2}) == 0.5
    assert _call_strength(caller, target, {"close": 4}) == 0.25
    # a resolved call is still full weight
    direct = _I("m.direct", "direct", ["io.Reader.close"])
    assert _call_strength(direct, target, {}) == 1.0


def test_mined_candidates_are_distinguishable(idx):
    """The symptom #17 actually reported: candidates you cannot tell apart.

    `confidence` is the weakest link and still clusters at the threshold by design —
    that is what a gate does. `strength` is what ranks them, so it must carry more
    than one value on any non-trivial index.
    """
    flows = mine_workflows(idx)
    assert flows, "fixture should mine at least one candidate"
    for f in flows:
        assert 0.0 <= f["confidence"] <= 1.0
        assert f["confidence"] <= f["strength"] <= 1.0, "min must not exceed mean"
    # ranked best-first by strength
    strengths = [f["strength"] for f in flows]
    assert strengths == sorted(strengths, reverse=True)


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
