"""Shared helpers for the data-structure translation round (gx/datastructs).

Sealed with the round: a fixer cannot change what these helpers check. Everything goes
through the `spindlebox` CLI (`python -m spindlebox`), never internal APIs, with the
registry in a temp SPINDLEBOX_HOME and plugins off, so the round tests the product as
a caller sees it.

The canonical text form of an index `types` entry (register DS-SHAPE):
  record <Name>[<T,...>]{<field>:<type>,...}                 fields in declaration order
  variant <Name>[<T,...>]{<Variant>[{<field>:<type>,...}],...}  variants in declaration order
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROUND = Path(__file__).parent
INPUTS = ROUND / "corpus" / "inputs"
LANGS = ["python", "go", "rust", "typescript", "java"]
MODEL = ["Money", "LineItem", "Status", "Payment", "Order", "Tree", "Page"]

# DS-PY/GO/RS/JV: the seven model types, in canonical form.
EXPECTED = {
    "Money": "record Money{amount:i64,currency:str}",
    "LineItem": "record LineItem{sku:str,qty:i64,price:obj:Money}",
    "Status": "variant Status{Pending,Paid,Shipped}",
    "Payment": "variant Payment{Card{last4:str},Transfer{iban:str},Cash}",
    "Order": "record Order{id:str,items:list<obj:LineItem>,status:obj:Status,"
             "payment:option<obj:Payment>,tags:map<str,list<str>>}",
    "Tree": "record Tree<T>{value:typevar:T,children:list<obj:Tree<typevar:T>>}",
    "Page": "record Page<T>{items:list<typevar:T>,next:option<str>}",
}
# DS-TS: TypeScript has one numeric type, `number`, which core-1 normalizes to f64.
EXPECTED_TS = {**EXPECTED,
               "Money": "record Money{amount:f64,currency:str}",
               "LineItem": "record LineItem{sku:str,qty:f64,price:obj:Money}"}


def expected(lang: str) -> dict[str, str]:
    return EXPECTED_TS if lang == "typescript" else EXPECTED


def cli(args: list[str], home: Path, cwd: Path | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ, SPINDLEBOX_HOME=str(home), SPINDLEBOX_PLUGINS="none")
    return subprocess.run([sys.executable, "-m", "spindlebox", *args], cwd=cwd, env=env,
                          capture_output=True, text=True, timeout=600)


def index_dir(src: Path, work: Path, name: str) -> dict:
    """Copy `src` to work/<name>, index it through the CLI, return the parsed index."""
    proj = work / name
    shutil.copytree(src, proj)
    r = cli(["index", str(proj)], work / "home")
    assert r.returncode == 0, f"spindlebox index {name} failed:\n{r.stdout}\n{r.stderr}"
    return json.loads((proj / ".spi" / "index.json").read_text())


def generate(lang: str, target: str, work: Path) -> Path:
    """Index the `lang` model, generate `target` from it, return the output dir."""
    name = f"ds_{lang}"
    index_dir(INPUTS / lang, work, name)
    out = work / f"gen_{lang}_to_{target}"
    r = cli(["generate", "--lang", target, "--project", name, "--out", str(out)], work / "home")
    assert r.returncode == 0, f"generate {lang}->{target} failed:\n{r.stdout}\n{r.stderr}"
    assert out.exists() and any(out.rglob("*")), f"generate {lang}->{target} wrote nothing"
    return out


def canonical(t: dict) -> str:
    tp = f"<{','.join(t['type_params'])}>" if t.get("type_params") else ""
    if t["kind"] == "record":
        body = ",".join(f"{f['name']}:{f['type']}" for f in t["fields"])
    elif t["kind"] == "variant":
        body = ",".join(
            v["name"] + ("{" + ",".join(f"{f['name']}:{f['type']}" for f in v["fields"]) + "}"
                         if v.get("fields") else "")
            for v in t["variants"])
    else:
        raise AssertionError(f"unknown type kind {t['kind']!r} for {t.get('name')}")
    return f"{t['kind']} {t['name']}{tp}{{{body}}}"


def model_types(index: dict) -> dict[str, str]:
    """name -> canonical form, for the seven model types found in the index."""
    out: dict[str, str] = {}
    for t in index.get("types", []):
        if t.get("name") in MODEL:
            assert t["name"] not in out, f"model type {t['name']} indexed twice"
            out[t["name"]] = canonical(t)
    return out


OBJ_REF = re.compile(r"obj:([A-Za-z_]\w*)")


@pytest.fixture(scope="session")
def work(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("gx_datastructs")


@pytest.fixture(scope="session")
def indexes(work) -> dict[str, dict]:
    return {lang: index_dir(INPUTS / lang, work / "src", f"ds_{lang}") for lang in LANGS}
