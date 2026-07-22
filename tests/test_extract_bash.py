from pathlib import Path

import pytest

from spindlebox.extract import build_index

FIXTURE = Path(__file__).parent / "fixtures" / "miniproj_bash"


@pytest.fixture(scope="module")
def idx():
    return build_index(FIXTURE, project_name="miniproj_bash", langs=["bash"])


def by_addr(idx, address):
    item = idx.item_by_address(address)
    assert item is not None, f"no item at {address}; have {[i.address for i in idx.items]}"
    return item


def test_functions_extracted(idx):
    deploy = by_addr(idx, "deploy.deploy")
    assert deploy.kind == "function"
    assert deploy.language == "bash"
    assert deploy.doc == "Deploy the thing to the target environment."


def test_degenerate_signature(idx):
    deploy = by_addr(idx, "deploy.deploy")
    assert deploy.sig_class == "sig:*list<str>->result<str,i64>"


def test_env_var(idx):
    deploy = by_addr(idx, "deploy.deploy")
    assert "DEPLOY_ENV" in deploy.deps.env_vars


def test_intra_file_call(idx):
    deploy = by_addr(idx, "deploy.deploy")
    assert "deploy.build" in deploy.deps.calls
