"""Differential tests: the profile-driven walker must reproduce the legacy
Go and Bash extractors exactly, on every fixture file of those languages."""

from pathlib import Path

import pytest

from spindlebox.extract.base import ALL_LANGS, EXT_MAP
from spindlebox.extract.bash_lang import extract_bash_file
from spindlebox.extract.go_lang import extract_go_file
from spindlebox.extract.profile_lang import extract_with_profile
from spindlebox.extract.profile_registry import profile_for

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture_files(suffix: str) -> list[Path]:
    files = [p for p in FIXTURES.rglob(f"*{suffix}") if ".spi" not in p.parts]
    assert files, f"no {suffix} fixture files found"
    return files


@pytest.mark.parametrize("path", _fixture_files(".go"), ids=lambda p: p.name)
def test_go_differential(path):
    src = path.read_text()
    rel = path.name
    legacy = extract_go_file(rel, src)
    profiled = extract_with_profile(profile_for("go"), rel, src)
    assert profiled == legacy


@pytest.mark.parametrize("path", _fixture_files(".sh"), ids=lambda p: p.name)
def test_bash_differential(path):
    src = path.read_text()
    rel = path.name
    legacy = extract_bash_file(rel, src)
    profiled = extract_with_profile(profile_for("bash"), rel, src)
    assert profiled == legacy


@pytest.mark.parametrize("path", _fixture_files(".rs"), ids=lambda p: p.name)
def test_rust_differential(path):
    from spindlebox.extract.rust_lang import extract_rust_file
    src = path.read_text()
    rel = path.name
    legacy = extract_rust_file(rel, src)
    profiled = extract_with_profile(profile_for("rust"), rel, src)
    assert profiled == legacy


def _js_fixture_files():
    out = []
    for suffix, lang in ((".js", "javascript"), (".jsx", "javascript"),
                         (".mjs", "javascript"), (".ts", "typescript"),
                         (".tsx", "typescript")):
        out += [(p, lang) for p in FIXTURES.rglob(f"*{suffix}") if ".spi" not in p.parts]
    assert out, "no js/ts fixture files found"
    return out


@pytest.mark.parametrize("path,lang", _js_fixture_files(), ids=lambda v: getattr(v, "name", v))
def test_js_ts_differential(path, lang):
    from spindlebox.extract.js_lang import extract_js_file
    src = path.read_text()
    rel = path.name
    legacy = extract_js_file(rel, src, lang)
    profiled = extract_with_profile(profile_for(lang), rel, src)
    assert profiled == legacy


def test_profiles_registered():
    for lang in ("go", "bash", "java", "rust", "javascript", "typescript"):
        assert profile_for(lang).walker, lang


def test_java_registered_in_language_tables():
    assert EXT_MAP[".java"] == "java"
    assert "java" in ALL_LANGS
