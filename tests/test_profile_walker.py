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


def test_profiles_registered():
    assert profile_for("go").walker
    assert profile_for("bash").walker
    assert profile_for("java").walker


def test_java_registered_in_language_tables():
    assert EXT_MAP[".java"] == "java"
    assert "java" in ALL_LANGS
