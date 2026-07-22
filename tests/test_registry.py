from spindlebox.registry import list_projects, register, unregister


def test_register_and_list(tmp_path, monkeypatch):
    monkeypatch.setenv("SPINDLEBOX_HOME", str(tmp_path / "fhome"))
    register("demo", "/tmp/demo", "/tmp/demo/.spi/index.json")
    projects = list_projects()
    assert projects["demo"]["root"] == "/tmp/demo"
    assert projects["demo"]["index"] == "/tmp/demo/.spi/index.json"
    assert "last_indexed" in projects["demo"]


def test_reregister_updates(tmp_path, monkeypatch):
    monkeypatch.setenv("SPINDLEBOX_HOME", str(tmp_path / "fhome"))
    register("demo", "/a", "/a/.spi/index.json")
    register("demo", "/b", "/b/.spi/index.json")
    assert list_projects()["demo"]["root"] == "/b"


def test_unregister(tmp_path, monkeypatch):
    monkeypatch.setenv("SPINDLEBOX_HOME", str(tmp_path / "fhome"))
    register("demo", "/a", "/a/.spi/index.json")
    unregister("demo")
    assert "demo" not in list_projects()


def test_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("SPINDLEBOX_HOME", str(tmp_path / "fhome"))
    assert list_projects() == {}


def test_legacy_env_var_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("SPINDLEBOX_HOME", raising=False)
    monkeypatch.setenv("FINDEXER_HOME", str(tmp_path / "legacy_home"))
    register("demo", "/a", "/a/.spi/index.json")
    assert list_projects()["demo"]["root"] == "/a"
