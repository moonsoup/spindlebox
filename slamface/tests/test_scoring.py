from slamface.harness.scoring import score_run

PROFILE = {
    "index_success": 25, "zero_tracebacks": 25, "validate_expected": 15,
    "generate_compiles": 20, "dispatch_roundtrip": 5, "aux_probes": 10,
}


def rec(stage, status):
    return {"stage": stage, "status": status}


def test_all_green_is_100():
    records = [rec("index", "ok"), rec("validate", "ok"),
               rec("cargo_check", "ok"), rec("dispatch", "ok")]
    result = score_run(records, PROFILE)
    assert result["score"] == 100.0


def test_unevaluated_criteria_drop_from_denominator():
    # no cargo, no dispatch, no aux → only index/tracebacks/validate count
    records = [rec("index", "ok"), rec("validate", "ok")]
    result = score_run(records, PROFILE)
    assert result["score"] == 100.0
    assert result["criteria"]["generate_compiles"]["evaluated"] is False


def test_partial_credit():
    records = [rec("index", "ok"), rec("index", "fail"),
               rec("validate", "ok"), rec("validate", "ok")]
    result = score_run(records, PROFILE)
    # index 25*0.5 + tracebacks 25*1.0 + validate 15*1.0 over 65
    assert result["score"] == round(100 * (12.5 + 25 + 15) / 65, 2)


def test_traceback_kills_zero_tracebacks():
    records = [rec("index", "ok"), rec("generate_rust", "error")]
    result = score_run(records, PROFILE)
    assert result["criteria"]["zero_tracebacks"]["fraction"] == 0.5


def test_skips_ignored():
    records = [rec("index", "ok"), rec("cargo_check", "skip")]
    result = score_run(records, PROFILE)
    assert result["criteria"]["generate_compiles"]["evaluated"] is False
