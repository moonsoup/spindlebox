import json

from slamface.ops.harvest_logs import harvest, issue_signatures, parse_failures


def write_failures(tmp_path, run_id, records):
    lines = []
    for r in records:
        lines.append(json.dumps(r))
    (tmp_path / f"failures-{run_id}.jsonl").write_text("\n".join(lines) + "\n")


def rec(sig, run_id, repo="self", stage="cargo_check", cls="NonzeroExit"):
    return {"run_id": run_id, "tier": 0, "repo": repo, "stage": stage,
            "error": {"signature": sig, "class": cls, "trace_head": "x in y",
                      "log_excerpt": "boom"}}


def test_grouping_by_signature(tmp_path):
    write_failures(tmp_path, "r-1", [rec("aaaaaaaaaaaa", "r-1"),
                                     rec("aaaaaaaaaaaa", "r-1", repo="other"),
                                     rec("bbbbbbbbbbbb", "r-1")])
    groups = parse_failures(tmp_path)
    assert set(groups) == {"aaaaaaaaaaaa", "bbbbbbbbbbbb"}
    assert groups["aaaaaaaaaaaa"]["count"] == 2
    assert groups["aaaaaaaaaaaa"]["repos"] == ["self", "other"]


def test_issue_signature_extraction():
    issues = [{"number": 7, "title": "[slamface:aaaaaaaaaaaa] KeyError in x", "state": "OPEN"},
              {"number": 3, "title": "unrelated", "state": "OPEN"}]
    assert issue_signatures(issues) == {"aaaaaaaaaaaa": {"number": 7, "state": "open"}}


def test_harvest_categorization(tmp_path):
    write_failures(tmp_path, "r-2", [rec("aaaaaaaaaaaa", "r-2"),
                                     rec("bbbbbbbbbbbb", "r-2"),
                                     rec("cccccccccccc", "r-2")])
    issues = [{"number": 1, "title": "[slamface:aaaaaaaaaaaa] x", "state": "OPEN"},
              {"number": 2, "title": "[slamface:bbbbbbbbbbbb] y", "state": "CLOSED"}]
    result = harvest(tmp_path, issues)
    assert [g["signature"] for g in result["new"]] == ["cccccccccccc"]
    assert result["recurring"][0]["issue"] == 1
    assert result["regressed"][0]["issue"] == 2


def test_since_run_filter(tmp_path):
    write_failures(tmp_path, "r-1", [rec("aaaaaaaaaaaa", "r-1")])
    write_failures(tmp_path, "r-3", [rec("bbbbbbbbbbbb", "r-3")])
    result = harvest(tmp_path, [], since_run="r-2")
    assert [g["signature"] for g in result["new"]] == ["bbbbbbbbbbbb"]
