from types import SimpleNamespace

from slamface.ops.file_issues import repro_marker
from slamface.ops.verify_fix import verify

BODY = "evidence...\n" + repro_marker("cargo check --quiet", "/tmp/gen_self") + "\n"
HEAD = "a" * 40


class Gh:
    def __init__(self, body=BODY):
        self.calls = []
        self.body = body

    def json(self, args, timeout=60):
        return {"body": self.body, "title": "t", "state": "OPEN"}

    def run(self, args, timeout=60):
        self.calls.append(args)
        return ""


def make_exec(fail_on: int | None = None):
    counter = {"n": 0}

    def exec_fn(cmd, workdir=None, timeout=900):
        counter["n"] += 1
        code = 1 if fail_on is not None and counter["n"] == fail_on else 0
        return SimpleNamespace(returncode=code, stdout="ok", stderr="")
    return exec_fn


def ssh_fn(cmd, timeout=120):
    return SimpleNamespace(returncode=0, stdout="sha256:img\n", stderr="")


def test_closes_after_three_green():
    gh = Gh()
    result = verify(5, exec_fn=make_exec(), gh_json_fn=gh.json, gh_fn=gh.run,
                    ssh_fn=ssh_fn, vps_head_fn=lambda: HEAD, origin_head_fn=lambda: HEAD)
    assert result["verified"] is True
    close = next(c for c in gh.calls if c[:2] == ["issue", "close"])
    assert HEAD in close[close.index("--comment") + 1]


def test_refuses_close_on_any_failure():
    gh = Gh()
    result = verify(5, exec_fn=make_exec(fail_on=2), gh_json_fn=gh.json, gh_fn=gh.run,
                    ssh_fn=ssh_fn, vps_head_fn=lambda: HEAD, origin_head_fn=lambda: HEAD)
    assert result["verified"] is False
    assert not any(c[:2] == ["issue", "close"] for c in gh.calls)
    assert any("state:fix-failed-verify" in c for c in gh.calls
               if c[:2] == ["issue", "edit"])


def test_refuses_when_deploy_pending():
    gh = Gh()
    result = verify(5, exec_fn=make_exec(), gh_json_fn=gh.json, gh_fn=gh.run,
                    ssh_fn=ssh_fn, vps_head_fn=lambda: "b" * 40, origin_head_fn=lambda: HEAD)
    assert result["verified"] is False and "deploy pending" in result["reason"]
    assert gh.calls == []


def test_refuses_without_marker():
    gh = Gh(body="no marker here")
    result = verify(5, exec_fn=make_exec(), gh_json_fn=gh.json, gh_fn=gh.run,
                    ssh_fn=ssh_fn, vps_head_fn=lambda: HEAD, origin_head_fn=lambda: HEAD)
    assert result["verified"] is False and "marker" in result["reason"]
    assert gh.calls == []


def test_infra_error_does_not_reopen():
    """An exec/OCI error (exit 128, relative cwd) is not a reproduction — verify
    must not label/reopen on it (pydantic T3: #2 false reopen)."""
    from types import SimpleNamespace
    gh = Gh()

    def infra_exec(cmd, workdir=None, timeout=900):
        return SimpleNamespace(returncode=128, stdout="",
                               stderr="OCI runtime exec failed: Cwd must be an absolute path")
    result = verify(5, exec_fn=infra_exec, gh_json_fn=gh.json, gh_fn=gh.run,
                    ssh_fn=ssh_fn, vps_head_fn=lambda: HEAD, origin_head_fn=lambda: HEAD)
    assert result["verified"] is False and "cannot verify" in result["reason"]
    assert not any(c[:2] == ["issue", "close"] for c in gh.calls)
    assert not any("fix-failed-verify" in str(c) for c in gh.calls)
