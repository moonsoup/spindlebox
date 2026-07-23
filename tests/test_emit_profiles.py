"""Differential tests: the profile-driven emit engine must reproduce the legacy
Rust backend byte-for-byte on every fixture project. That parity is what licenses
trusting the engine for languages that exist only as emit profiles (Java)."""

from pathlib import Path

import pytest

from spindlebox.extract import build_index
from spindlebox.generate import BACKENDS, GenOptions
from spindlebox.generate.profile_backend import EMIT_DIR, load_emit_backends
from spindlebox.generate.rust_backend import RustBackend

FIXTURES = Path(__file__).parent / "fixtures"
PROJECTS = sorted(
    p.name for p in FIXTURES.iterdir()
    if p.is_dir() and any(f.suffix != ".json" for f in p.rglob("*") if f.is_file())
)


@pytest.mark.parametrize("project", PROJECTS)
def test_rust_engine_differential(project):
    idx = build_index(FIXTURES / project, project_name=project)
    legacy = {f.relpath: f.content for f in RustBackend().generate(idx, GenOptions())}
    engine_cls = load_emit_backends()["rust"]
    profiled = {f.relpath: f.content for f in engine_cls().generate(idx, GenOptions())}
    assert profiled == legacy


def test_rust_backend_stays_legacy():
    # never-remove: 'rust' must keep resolving to the hand-written backend
    assert BACKENDS["rust"] is RustBackend


def test_java_backend_registered_from_profile():
    assert "java" in BACKENDS
    assert (EMIT_DIR / "java.json").exists()
    import spindlebox.generate as pkg
    assert not (Path(pkg.__file__).parent / "java_backend.py").exists()
