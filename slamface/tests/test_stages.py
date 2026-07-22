import os
from pathlib import Path

import pytest

from slamface.harness.stages import parse_traceback, run_stage

TB = '''Traceback (most recent call last):
  File "/app/spindlebox/cli.py", line 82, in cmd_index
    idx.save(index_path)
  File "/app/spindlebox/generate/rust_backend.py", line 87, in emit_op_array
    x = d["sig_class"]
KeyError: 'sig_class'
'''


def test_parse_traceback():
    tb = parse_traceback(TB)
    assert tb["class"] == "KeyError"
    assert tb["trace_head"] == "/app/spindlebox/generate/rust_backend.py:87 in emit_op_array"


def test_parse_no_traceback():
    assert parse_traceback("error: something bad\n") is None


def test_run_stage_ok(tmp_path):
    record = run_stage("t", ["python3", "-c", "print('hi')"], tmp_path, "python")
    assert record["status"] == "ok" and record["exit_code"] == 0


def test_run_stage_traceback_is_error(tmp_path):
    record = run_stage("t", ["python3", "-c", "raise ValueError('boom')"], tmp_path, "python")
    assert record["status"] == "error"
    assert record["error"]["class"] == "ValueError"
    assert len(record["error"]["signature"]) == 12


def test_run_stage_nonzero_is_fail(tmp_path):
    record = run_stage("t", ["python3", "-c", "import sys; sys.exit(3)"], tmp_path, "python")
    assert record["status"] == "fail"
    assert record["error"]["class"] == "NonzeroExit"


def test_run_stage_expected_nonzero_ok(tmp_path):
    record = run_stage("t", ["python3", "-c", "import sys; sys.exit(1)"], tmp_path, "python",
                       expect_exit=(0, 1))
    assert record["status"] == "ok"


@pytest.mark.skipif(os.environ.get("SLAMFACE_INTEGRATION") != "1",
                    reason="set SLAMFACE_INTEGRATION=1 to run the full T0 tier locally")
def test_tier0_integration(tmp_path):
    from slamface.harness.run_tier import run_tier
    repo_root = Path(__file__).resolve().parents[2]
    result = run_tier(0, tmp_path, repo_root)
    assert result["stages"] > 10
    assert result["score"] >= 95, result
