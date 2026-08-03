"""Staleness detection: an index must never hand back a span it can't vouch for.

Regression cover for #15 — 18% of stored spans in an 11-day-old index no longer
pointed at their declaration, and nothing detected it.
"""

import argparse
import os

import pytest
from test_schema import make_index, make_item

from spindlebox import staleness
from spindlebox.schema import ScaIndex


def write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


@pytest.fixture
def project(tmp_path):
    """An index whose single item lives in src/mod.py, with file metadata recorded."""
    write(tmp_path, "src/mod.py", "def f(path):\n    return []\n")
    index = make_index()
    index.root = str(tmp_path)
    index.files = staleness.snapshot_files(tmp_path, ["src/mod.py"])
    return tmp_path, index


class TestFileDigest:
    def test_has_sha256_prefix(self, tmp_path):
        p = write(tmp_path, "a.py", "x = 1\n")
        assert staleness.file_digest(p).startswith("sha256:")

    def test_is_stable_for_identical_content(self, tmp_path):
        a = write(tmp_path, "a.py", "x = 1\n")
        b = write(tmp_path, "b.py", "x = 1\n")
        assert staleness.file_digest(a) == staleness.file_digest(b)

    def test_changes_with_content(self, tmp_path):
        p = write(tmp_path, "a.py", "x = 1\n")
        before = staleness.file_digest(p)
        p.write_text("x = 2\n", encoding="utf-8")
        assert staleness.file_digest(p) != before

    def test_missing_file_returns_none(self, tmp_path):
        assert staleness.file_digest(tmp_path / "nope.py") is None


class TestSnapshotFiles:
    def test_records_hash_mtime_and_size(self, tmp_path):
        write(tmp_path, "a.py", "x = 1\n")
        snap = staleness.snapshot_files(tmp_path, ["a.py"])
        assert set(snap["a.py"]) == {"hash", "mtime", "size"}
        assert snap["a.py"]["size"] == 6

    def test_skips_files_that_do_not_exist(self, tmp_path):
        write(tmp_path, "a.py", "x = 1\n")
        snap = staleness.snapshot_files(tmp_path, ["a.py", "ghost.py"])
        assert "ghost.py" not in snap
        assert "a.py" in snap

    def test_empty_list_yields_empty_snapshot(self, tmp_path):
        assert staleness.snapshot_files(tmp_path, []) == {}


class TestStaleReport:
    def test_clean_project_reports_nothing_stale(self, project):
        root, index = project
        report = staleness.stale_report(index, root)
        assert report["ok"] is True
        assert report["changed"] == [] and report["missing"] == []

    def test_detects_changed_content(self, project):
        root, index = project
        write(root, "src/mod.py", "def f(path):\n    return ['changed']\n")
        report = staleness.stale_report(index, root)
        assert report["ok"] is False
        assert report["changed"] == ["src/mod.py"]

    def test_detects_deleted_file(self, project):
        root, index = project
        os.remove(root / "src/mod.py")
        report = staleness.stale_report(index, root)
        assert report["ok"] is False
        assert report["missing"] == ["src/mod.py"]

    def test_mtime_change_alone_is_not_stale(self, project):
        """Content hash is authoritative — `git checkout` bumps mtime, not content."""
        root, index = project
        p = root / "src/mod.py"
        os.utime(p, (0, 0))
        report = staleness.stale_report(index, root)
        assert report["ok"] is True
        assert report["changed"] == []

    def test_detects_added_files_when_current_list_given(self, project):
        root, index = project
        write(root, "src/new.py", "def g():\n    pass\n")
        report = staleness.stale_report(index, root, current=["src/mod.py", "src/new.py"])
        assert report["added"] == ["src/new.py"]
        assert report["ok"] is False

    def test_added_not_reported_without_current_list(self, project):
        root, index = project
        write(root, "src/new.py", "def g():\n    pass\n")
        report = staleness.stale_report(index, root)
        assert report["added"] == []
        assert report["ok"] is True

    def test_legacy_index_without_metadata_is_flagged(self, tmp_path):
        """Pre-existing indexes carry no `files` map — that is itself unverifiable."""
        index = make_index()
        index.root = str(tmp_path)
        report = staleness.stale_report(index, tmp_path)
        assert report["has_metadata"] is False
        assert report["ok"] is False

    def test_empty_project_is_up_to_date_not_unverifiable(self, tmp_path):
        """#19 — an empty project and a pre-1.3.0 index both load as files == {},
        because `from_dict` reads a missing "files" key as {}. The version string
        already distinguishes them, so no schema change is needed.

        Before this, `spindlebox stale` on an empty project exited 1 telling the user
        to re-index — which produced the identical empty map and the same failure.
        """
        index = make_index()
        index.root = str(tmp_path)
        index.files = {}
        index.spindlebox_version = "1.3.0"      # tracking was active; {} is a real answer
        report = staleness.stale_report(index, tmp_path)
        assert report["has_metadata"] is True
        assert report["ok"] is True
        assert report["indexed_count"] == 0
        assert "up to date" in staleness.format_report(report, tmp_path)

    def test_pre_tracking_version_still_flagged_even_at_1_2(self, tmp_path):
        """The boundary is 1.3.0 exactly — 1.2.x predates the files map."""
        index = make_index()
        index.root = str(tmp_path)
        index.files = {}
        index.spindlebox_version = "1.2.0"
        assert staleness.stale_report(index, tmp_path)["has_metadata"] is False

    def test_malformed_version_does_not_crash(self, tmp_path):
        """A bad version string must degrade to "cannot vouch", never raise."""
        index = make_index()
        index.root = str(tmp_path)
        index.files = {}
        index.spindlebox_version = "not-a-version"
        assert staleness.stale_report(index, tmp_path)["has_metadata"] is False

    def test_report_records_whether_new_files_were_checked(self, project):
        """STALE-01 — `added: []` alone cannot distinguish "no new files" from "new
        files were never looked for", and the default never looks. #15 was 18% wrong
        spans AND 36% missing files; only the first half is caught by default.
        """
        root, index = project
        write(root, "src/new.py", "def g():\n    pass\n")

        default = staleness.stale_report(index, root)
        assert default["ok"] is True                      # unchanged behaviour
        assert default["checked_new"] is False
        assert "new files not checked" in staleness.format_report(default, root)

        checked = staleness.stale_report(index, root, current=["src/mod.py", "src/new.py"])
        assert checked["checked_new"] is True
        assert checked["added"] == ["src/new.py"]
        assert "new files not checked" not in staleness.format_report(checked, root)


class TestIsStale:
    def test_false_for_untouched_file(self, project):
        root, index = project
        assert staleness.is_stale(index, root, "src/mod.py") is False

    def test_true_after_edit(self, project):
        root, index = project
        write(root, "src/mod.py", "def f(path):\n    return [1]\n")
        assert staleness.is_stale(index, root, "src/mod.py") is True

    def test_true_when_file_not_in_metadata(self, project):
        root, index = project
        assert staleness.is_stale(index, root, "src/unknown.py") is True

    def test_true_for_legacy_index(self, tmp_path):
        index = make_index()
        assert staleness.is_stale(index, tmp_path, "src/mod.py") is True


class TestStaleItems:
    def test_names_items_whose_file_changed(self, project):
        root, index = project
        write(root, "src/mod.py", "def f(path):\n    return [1]\n")
        stale = staleness.stale_items(index, root)
        assert [i.address for i in stale] == ["src.mod.f"]

    def test_empty_when_clean(self, project):
        root, index = project
        assert staleness.stale_items(index, root) == []

    def test_items_from_untracked_files_count_as_stale(self, project):
        root, index = project
        extra = make_item(ordinal=1, address="src.other.g")
        extra.file = "src/other.py"
        index.items.append(extra)
        stale = staleness.stale_items(index, root)
        assert [i.address for i in stale] == ["src.other.g"]


class TestSpanOutput:
    """`show --span` exists so targeted reads never need an ad-hoc JSON pipe."""

    def test_emits_tab_separated_file_start_end_address(self, project, capsys, monkeypatch):
        from spindlebox import cli

        root, index = project
        monkeypatch.setattr(cli, "_load_project", lambda args: (index, root))
        args = argparse.Namespace(
            selector="src.mod.f", project=None, path=None, group=None,
            sig_class=None, lang=None, name=None, state_capture=None,
            span=True, deps=False, full=False, json=False, fail_on_stale=False,
        )
        assert cli.cmd_show(args) == 0
        line = capsys.readouterr().out.strip()
        assert line.split("\t") == ["src/mod.py", "1", "5", "src.mod.f"]


class TestSchemaRoundTrip:
    def test_files_map_survives_save_and_load(self, project, tmp_path):
        root, index = project
        out = tmp_path / "idx" / "index.json"
        index.save(out)
        loaded = ScaIndex.load(out)
        assert loaded.files == index.files

    def test_index_without_files_key_loads_as_empty(self, tmp_path):
        index = make_index()
        out = tmp_path / "index.json"
        data = index.to_dict()
        del data["files"]
        import json

        out.write_text(json.dumps(data), encoding="utf-8")
        loaded = ScaIndex.load(out)
        assert loaded.files == {}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
