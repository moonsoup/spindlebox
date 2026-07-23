from slamface.ops.report import render, render_csv, render_html

SCORES = [
    {"run_id": "r-1", "tier": 0, "score": 87.5, "threshold": 95, "green": False,
     "stages": 30, "failures": 3, "generated_at": "2026-07-22T20:00:00",
     "spindlebox_version": "0.5.0"},
    {"run_id": "r-2", "tier": 1, "score": 100.0, "threshold": 90, "green": True,
     "stages": 36, "failures": 0, "generated_at": "2026-07-22T23:53:00",
     "spindlebox_version": "0.8.0"},
]
ISSUES = {"total": 2, "open": [11], "closed": [10]}
LOOP = {"run_count": 12, "tier": 1, "consecutive_green": 1}


def test_render_markdown_unchanged_shape():
    out = render(SCORES, ISSUES, LOOP)
    assert "# slamface checkpoint report" in out
    assert "| r-2 | 1 | 100.0 | 90 | ✅ | 36 | 0 |" in out


def test_render_csv():
    out = render_csv(SCORES)
    lines = out.strip().splitlines()
    assert lines[0] == ("run_id,tier,score,threshold,green,stages,failures,"
                        "generated_at,spindlebox_version")
    assert lines[1].startswith("r-1,0,87.5,95,False,30,3,")
    assert lines[2].startswith("r-2,1,100.0,90,True,36,0,")


def test_render_html():
    out = render_html(SCORES, ISSUES, LOOP)
    assert out.startswith("<!doctype html>")
    assert "<td>r-2</td>" in out
    assert "100.0" in out
    # printable → PDF via browser; must be self-contained
    assert "http" not in out.split("</style>")[0]
