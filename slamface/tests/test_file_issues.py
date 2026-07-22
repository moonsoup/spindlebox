from types import SimpleNamespace

from slamface.ops.file_issues import process, repro_marker


def group(sig, cmd="spindlebox index /x"):
    return {"signature": sig, "stage": "index", "error_class": "KeyError",
            "trace_head": "spindlebox/x.py in f", "tier": 0, "count": 1,
            "repos": ["self"], "run_ids": ["r-1"],
            "sample": {"cmd": cmd, "repro_cmd": f"cd /corpus/self && {cmd}",
                       "repo": "self", "error": {"log_excerpt": "trace..."}}}


def failing_exec(cmd, workdir=None, timeout=900):
    return SimpleNamespace(returncode=1, stdout="", stderr="KeyError: boom")


def passing_exec(cmd, workdir=None, timeout=900):
    return SimpleNamespace(returncode=0, stdout="fine", stderr="")


class GhRecorder:
    def __init__(self):
        self.calls = []

    def __call__(self, args, timeout=60):
        self.calls.append(args)
        return ""


def test_new_issue_filed_only_after_reproduction():
    gh = GhRecorder()
    outcome = process({"new": [group("aaaaaaaaaaaa")], "recurring": [], "regressed": []},
                      tier=0, exec_fn=failing_exec, gh_fn=gh)
    assert outcome["filed"] == ["aaaaaaaaaaaa"]
    create = next(c for c in gh.calls if c[:2] == ["issue", "create"])
    body = create[create.index("--body") + 1]
    assert "slamface-repro" in body and "Fresh reproduction" in body


def test_flaky_not_filed():
    gh = GhRecorder()
    outcome = process({"new": [group("aaaaaaaaaaaa")], "recurring": [], "regressed": []},
                      tier=0, exec_fn=passing_exec, gh_fn=gh)
    assert outcome["filed"] == [] and outcome["flaky"] == ["aaaaaaaaaaaa"]
    assert not any(c[:2] == ["issue", "create"] for c in gh.calls)


def test_cap_defers_excess():
    gh = GhRecorder()
    new = [group(f"{i:012x}") for i in range(7)]
    outcome = process({"new": new, "recurring": [], "regressed": []},
                      tier=1, max_new=5, exec_fn=failing_exec, gh_fn=gh)
    assert len(outcome["filed"]) == 5 and len(outcome["deferred"]) == 2


def test_recurring_gets_comment_not_issue():
    gh = GhRecorder()
    outcome = process({"new": [], "recurring": [{**group("aaaaaaaaaaaa"), "issue": 9}],
                       "regressed": []}, tier=0, exec_fn=failing_exec, gh_fn=gh)
    assert outcome["commented"] == [9]
    assert not any(c[:2] == ["issue", "create"] for c in gh.calls)


def test_regression_reopens():
    gh = GhRecorder()
    outcome = process({"new": [], "recurring": [],
                       "regressed": [{**group("bbbbbbbbbbbb"), "issue": 4}]},
                      tier=0, exec_fn=failing_exec, gh_fn=gh)
    assert outcome["reopened"] == [4]
    assert any(c[:2] == ["issue", "reopen"] for c in gh.calls)


def test_repro_marker_roundtrip():
    from slamface.ops.verify_fix import extract_repro
    body = "text\n" + repro_marker('spindlebox index "/x y"', "/corpus/self") + "\nmore"
    cmd, cwd = extract_repro(body)
    assert cmd == 'spindlebox index "/x y"' and cwd == "/corpus/self"


def test_reproduction_uses_standalone_repro_cmd():
    seen = []

    def exec_fn(cmd, workdir=None, timeout=900):
        seen.append(cmd)
        return SimpleNamespace(returncode=1, stdout="", stderr="err")

    gh = GhRecorder()
    process({"new": [group("eeeeeeeeeeee")], "recurring": [], "regressed": []},
            tier=0, exec_fn=exec_fn, gh_fn=gh)
    assert seen and seen[0].startswith("cd /corpus/self && ")


def test_no_repro_cmd_is_not_reproduced():
    """Drill finding: a record without a standalone repro_cmd must not falsely
    reproduce (no bare-cmd fallback)."""
    from slamface.ops.file_issues import reproduce_in_container
    g = {"sample": {"cmd": "cargo check", "error": {}}}  # no repro_cmd
    called = []
    reproduced, msg = reproduce_in_container(
        g, exec_fn=lambda c, **k: called.append(c))
    assert reproduced is False and called == []
