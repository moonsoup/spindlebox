"""A plugin's own data lives beside the index, and indexing leaves it alone.

`ScaIndex.load` drops keys it does not know and `save` rewrites the whole
document, so a plugin must never keep state inside index.json. It keeps it in
`.spi/plugins/<plugin>/`, and this pins that re-indexing does not disturb it --
and that index.json itself gains no new keys, because other projects' scripts
read that file by hand.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
FIXTURES = REPO / "tests" / "fixtures"

INDEX_KEYS = {
    "spi_version", "project", "type_vocabulary", "items", "groups",
    "signature_classes", "pipelines", "ctx_schema", "retired_ordinals",
    "parse_errors", "files",
}


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "miniproj_py"
    shutil.copytree(FIXTURES / "miniproj_py", root)
    shutil.rmtree(root / ".spi", ignore_errors=True)
    home = tmp_path / "home"

    def index():
        done = subprocess.run(
            [sys.executable, "-m", "spindlebox", "index", str(root)],
            capture_output=True, text=True, cwd=tmp_path,
            env={"PATH": "/usr/bin:/bin", "HOME": str(home),
                 "SPINDLEBOX_HOME": str(home), "SPINDLEBOX_PLUGINS": "none"})
        assert done.returncode == 0, done.stderr
        return done

    return root, index


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_plugin_state_survives_reindexing(project) -> None:
    root, index = project
    index()
    sidecar = root / ".spi" / "plugins" / "fake" / "state.json"
    sidecar.parent.mkdir(parents=True)
    sidecar.write_text(json.dumps({"kept": True}) + "\n")
    before = _digest(sidecar)

    index()

    assert sidecar.exists(), "re-indexing removed the plugin's state"
    assert _digest(sidecar) == before


def test_the_index_document_gains_no_new_keys(project) -> None:
    """Populous3D's spi-enrich.py and gate.py read this file by hand."""
    root, index = project
    index()
    written = json.loads((root / ".spi" / "index.json").read_text())
    assert set(written) == INDEX_KEYS
