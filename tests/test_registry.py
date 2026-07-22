from findexer.registry import list_projects, register, unregister


def test_register_and_list(tmp_path, monkeypatch):
    monkeypatch.setenv("FINDEXER_HOME", str(tmp_path / "fhome"))
    register("demo", "/tmp/demo", "/tmp/demo/.sca/index.json")
    projects = list_projects()
    assert projects["demo"]["root"] == "/tmp/demo"
    assert projects["demo"]["index"] == "/tmp/demo/.sca/index.json"
    assert "last_indexed" in projects["demo"]


def test_reregister_updates(tmp_path, monkeypatch):
    monkeypatch.setenv("FINDEXER_HOME", str(tmp_path / "fhome"))
    register("demo", "/a", "/a/.sca/index.json")
    register("demo", "/b", "/b/.sca/index.json")
    assert list_projects()["demo"]["root"] == "/b"


def test_unregister(tmp_path, monkeypatch):
    monkeypatch.setenv("FINDEXER_HOME", str(tmp_path / "fhome"))
    register("demo", "/a", "/a/.sca/index.json")
    unregister("demo")
    assert "demo" not in list_projects()


def test_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("FINDEXER_HOME", str(tmp_path / "fhome"))
    assert list_projects() == {}
