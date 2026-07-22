import json
from types import SimpleNamespace

import pytest

import slamface.ops.loop_once as lo

HEAD = "c" * 40


@pytest.fixture()
def loop_env(tmp_path, monkeypatch):
    monkeypatch.setattr(lo, "LOOP_STATE", tmp_path / "loop.json")
    lock = tmp_path / "lock.json"
    lock.write_text(json.dumps({
        "weights_profiles": {"default": {}},
        "tiers": {"0": {"threshold": 95, "weights_profile": "default", "targets": []},
                  "1": {"threshold": 90, "weights_profile": "default", "targets": []}},
    }))
    monkeypatch.setattr(lo, "LOCK_PATH", lock)
    state_dir = tmp_path / "state"
    (state_dir / "logs").mkdir(parents=True)
    return tmp_path, state_dir


def deps(state_dir, green=True, open_issues=None, failures_written=False):
    open_issues = open_issues or []
    run_line = ("SLAMFACE_RUN " + json.dumps(
        {"run_id": "r-x", "tier": 0, "score": 100.0 if green else 50.0,
         "threshold": 95, "green": green, "failures": 0}))

    def gh_json(args, timeout=60):
        if "--state" in args and args[args.index("--state") + 1] == "open":
            return [{"number": n, "title": f"[slamface:{'d' * 12}] x", "state": "OPEN"}
                    for n in open_issues]
        return [{"number": n, "title": f"[slamface:{'d' * 12}] x", "state": "OPEN"}
                for n in open_issues]

    return {
        "vps_head": lambda: HEAD,
        "origin_head": lambda: HEAD,
        "exec_fn": lambda cmd, timeout=3600, workdir=None: SimpleNamespace(
            returncode=0, stdout=run_line, stderr=""),
        "pull_state": lambda: state_dir,
        "gh_json": gh_json,
        "gh_run": lambda args, timeout=60: "",
        "verify": lambda n: {"verified": False},
    }


def test_deploy_pending_blocks(loop_env, capsys):
    _, state_dir = loop_env
    d = deps(state_dir)
    d["origin_head"] = lambda: "e" * 40
    status = lo.loop_once(tier=0, deps=d)
    assert status["next_action"] == "deploy_pending"
    assert "run_id" not in status


def test_green_run_counts_and_reruns(loop_env, capsys):
    _, state_dir = loop_env
    status = lo.loop_once(tier=0, deps=deps(state_dir))
    assert status["green"] is True
    assert status["consecutive_green"] == 1
    assert status["next_action"] == "rerun"
    out = capsys.readouterr().out
    assert out.startswith("SLAMFACE_STATUS ")


def test_promotion_after_two_greens(loop_env):
    _, state_dir = loop_env
    lo.loop_once(tier=0, deps=deps(state_dir))
    status = lo.loop_once(tier=0, deps=deps(state_dir))
    assert status["consecutive_green"] == 2
    assert status["next_action"] == "promote" and status["next_tier"] == 1


def test_open_issues_reset_green_streak(loop_env):
    _, state_dir = loop_env
    lo.loop_once(tier=0, deps=deps(state_dir))
    status = lo.loop_once(tier=0, deps=deps(state_dir, open_issues=[12]))
    assert status["consecutive_green"] == 0
    assert status["next_action"] == "fix #12"


def test_checkpoint_every_tenth_run(loop_env):
    _, state_dir = loop_env
    for _ in range(9):
        lo.loop_once(tier=0, deps=deps(state_dir))
    status = lo.loop_once(tier=0, deps=deps(state_dir))
    assert status["run_count"] == 10
    assert status["next_action"] == "checkpoint"


def test_escalate_when_no_next_tier(loop_env, monkeypatch):
    tmp, state_dir = loop_env
    lock = tmp / "lock.json"
    lock.write_text(json.dumps({
        "weights_profiles": {"default": {}},
        "tiers": {"0": {"threshold": 95, "weights_profile": "default", "targets": []}},
    }))
    lo.loop_once(tier=0, deps=deps(state_dir))
    status = lo.loop_once(tier=0, deps=deps(state_dir))
    assert status["next_action"] == "escalate"
