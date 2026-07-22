import json
import shutil
from pathlib import Path

import pytest

from findexer.cli import main

FIXTURE = Path(__file__).parent / "fixtures" / "miniproj_py"


@pytest.fixture()
def proj(tmp_path, monkeypatch):
    monkeypatch.setenv("FINDEXER_HOME", str(tmp_path / "fhome"))
    root = tmp_path / "miniproj_py"
    shutil.copytree(FIXTURE, root)
    return root


def test_index_creates_and_registers(proj, capsys):
    assert main(["index", str(proj)]) == 0
    assert (proj / ".sca" / "index.json").exists()
    out = capsys.readouterr().out
    assert "miniproj_py" in out
    assert main(["projects", "list"]) == 0
    assert "miniproj_py" in capsys.readouterr().out


def test_validate_ok(proj, capsys):
    main(["index", str(proj)])
    assert main(["validate", str(proj)]) == 0


def test_show_range_and_address(proj, capsys):
    main(["index", str(proj)])
    capsys.readouterr()
    assert main(["show", "0-3", "--project", "miniproj_py"]) == 0
    out = capsys.readouterr().out
    assert out.count("\n") >= 4
    assert main(["show", "pure.add", "--project", "miniproj_py", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data[0]["address"] == "pure.add"
    assert data[0]["sig_class"] == "sig:i64,i64->i64"


def test_show_group_filter(proj, capsys):
    main(["index", str(proj)])
    capsys.readouterr()
    assert main(["show", "util.io", "--project", "miniproj_py"]) == 0
    out = capsys.readouterr().out
    assert "read_lines" in out and "pure.add" not in out


def test_search_local_and_all(proj, capsys):
    main(["index", str(proj)])
    capsys.readouterr()
    assert main(["search", "read_lines", "--project", "miniproj_py"]) == 0
    assert "util.io.read_lines" in capsys.readouterr().out
    assert main(["search", "read_lines", "--all-projects"]) == 0
    out = capsys.readouterr().out
    assert "miniproj_py" in out and "util.io.read_lines" in out


def test_deps(proj, capsys):
    main(["index", str(proj)])
    capsys.readouterr()
    assert main(["deps", "app.home", "--project", "miniproj_py"]) == 0
    assert "FINDEXER_HOME" in capsys.readouterr().out


def test_deps_reverse(proj, capsys):
    main(["index", str(proj)])
    capsys.readouterr()
    assert main(["deps", "util.io.read_lines", "--project", "miniproj_py", "--reverse"]) == 0
    out = capsys.readouterr().out
    assert "util.io.Reader.read" in out


def test_call(proj, capsys):
    main(["index", str(proj)])
    capsys.readouterr()
    rc = main(["call", "pure.add", "--project", "miniproj_py", "--ctx", '{"a": 2, "b": 40}'])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["add_result"] == 42


def test_pipeline_define_and_check(proj, capsys):
    main(["index", str(proj)])
    capsys.readouterr()
    assert main(["pipeline", "define", "dbl", "app.double", "app.triple",
                 "--project", "miniproj_py"]) == 0
    assert main(["pipeline", "check", "dbl", "--project", "miniproj_py"]) == 0
    assert main(["pipeline", "list", "--project", "miniproj_py"]) == 0
    assert "dbl" in capsys.readouterr().out
    # unsound pipeline is rejected at define time with non-zero exit
    assert main(["pipeline", "define", "bad", "util.io.read_lines", "pure.greet",
                 "--project", "miniproj_py"]) != 0


def test_sticky_ordinals_on_reindex(proj, capsys):
    main(["index", str(proj)])
    capsys.readouterr()
    idx1 = json.loads((proj / ".sca" / "index.json").read_text())
    ord_by_addr = {i["address"]: i["ordinal"] for i in idx1["items"]}
    # add a new function at the top of a file — would shift naive ordinals
    app = proj / "app.py"
    app.write_text("def zeroth() -> int:\n    return 0\n\n\n" + app.read_text())
    main(["index", str(proj)])
    idx2 = json.loads((proj / ".sca" / "index.json").read_text())
    for item in idx2["items"]:
        if item["address"] in ord_by_addr:
            assert item["ordinal"] == ord_by_addr[item["address"]]


def test_validate_catches_tampering(proj, capsys):
    main(["index", str(proj)])
    p = proj / ".sca" / "index.json"
    data = json.loads(p.read_text())
    data["items"][0]["sig_class"] = "sig:bool->bool"
    p.write_text(json.dumps(data))
    assert main(["validate", str(proj)]) != 0
