"""Detect when an index no longer matches the files it describes.

The SPI stores a `span` per item. That span is what makes targeted reads
possible — locate an item, then read only its lines instead of the whole file.
But a span is only worth anything if the file has not moved underneath it, and
until this module existed nothing checked. An 11-day-old index was measured with
18% of its spans pointing at the wrong lines and 36% of the codebase missing
entirely, with no signal to the caller (#15).

Content hash is authoritative here; mtime is only a cheap pre-filter. A
`git checkout` or a `touch` rewrites mtime without changing a byte, and treating
that as a change would make every branch switch look like a full invalidation.
The reverse error — content changed but mtime preserved — is the one that
actually misleads, so the hash always decides.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from spindlebox.schema import Item, ScaIndex

#: Length of the hex digest kept per file. Matches the per-item `hash` field.
DIGEST_CHARS = 16

#: First release that recorded a `files` map. Below this, an absent map means
#: "built before tracking existed"; at or above it, an EMPTY map is a real
#: answer — the project genuinely has no indexable files (#19).
TRACKING_SINCE = (1, 3, 0)


def _version_tuple(version: str) -> tuple[int, ...]:
    """Lenient '1.3.0' -> (1, 3, 0). Unparseable segments count as 0 rather than
    raising: a malformed version must not crash a staleness check."""
    parts = []
    for segment in str(version).split("."):
        digits = "".join(c for c in segment if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def tracks_files(index: ScaIndex) -> bool:
    """Whether this index was built by a version that records file metadata.

    `ScaIndex.files` defaults to `{}` and `from_dict` loads a missing "files" key
    as `{}` too, so an empty map alone cannot distinguish a pre-1.3.0 index from
    an empty project. The version string already carries that distinction, so no
    schema change is needed.
    """
    return _version_tuple(index.spindlebox_version) >= TRACKING_SINCE


def file_digest(path: str | Path) -> str | None:
    """`sha256:<16 hex>` for a file's bytes, or None if it cannot be read."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    return f"sha256:{hashlib.sha256(data).hexdigest()[:DIGEST_CHARS]}"


def snapshot_files(root: str | Path, rel_paths) -> dict[str, dict]:
    """Record `{hash, mtime, size}` for each readable path, keyed by relative path.

    Paths that do not exist are omitted rather than recorded as empty — an index
    should not claim to describe a file it never read.
    """
    root = Path(root)
    snapshot: dict[str, dict] = {}
    for rel in rel_paths:
        abs_path = root / rel
        digest = file_digest(abs_path)
        if digest is None:
            continue
        stat = abs_path.stat()
        snapshot[str(rel)] = {
            "hash": digest,
            "mtime": stat.st_mtime,
            "size": stat.st_size,
        }
    return snapshot


def is_stale(index: ScaIndex, root: str | Path, rel_path: str) -> bool:
    """Whether `rel_path` has changed since indexing.

    Unknown files and indexes carrying no file metadata are treated as stale:
    when there is no way to verify, the honest answer is "do not trust this".
    """
    record = (index.files or {}).get(rel_path)
    if record is None:
        return True
    return file_digest(Path(root) / rel_path) != record.get("hash")


def stale_items(index: ScaIndex, root: str | Path) -> list[Item]:
    """Every item whose file can no longer be vouched for, in index order."""
    verdicts: dict[str, bool] = {}
    stale = []
    for item in index.items:
        if item.file not in verdicts:
            verdicts[item.file] = is_stale(index, root, item.file)
        if verdicts[item.file]:
            stale.append(item)
    return stale


def stale_report(index: ScaIndex, root: str | Path, current=None) -> dict:
    """Compare an index against the working tree.

    `current` is an optional list of relative paths the extractor would pick up
    today; supply it to surface files added since the last index. Without it
    `added` is empty, because absence of evidence is not evidence of absence.
    """
    root = Path(root)
    files = index.files or {}
    # An empty map is only "unverifiable" when the index predates tracking. From
    # 1.3.0 on it is a genuine answer: zero indexable files (#19).
    if not files and not tracks_files(index):
        return {
            "ok": False,
            "has_metadata": False,
            "changed": [],
            "missing": [],
            "added": [],
            "unchanged": [],
            "indexed_count": 0,
            "checked_new": current is not None,
        }

    changed, missing, unchanged = [], [], []
    for rel, record in files.items():
        digest = file_digest(root / rel)
        if digest is None:
            missing.append(rel)
        elif digest != record.get("hash"):
            changed.append(rel)
        else:
            unchanged.append(rel)

    added = sorted(set(current) - set(files)) if current is not None else []

    return {
        "ok": not (changed or missing or added),
        "has_metadata": True,
        "changed": sorted(changed),
        "missing": sorted(missing),
        "added": added,
        "unchanged": sorted(unchanged),
        "indexed_count": len(files),
        # Whether added-file detection actually ran. Without this a caller cannot
        # tell "no new files" from "new files were never looked for" — and the
        # default does not look (#15 was 18% wrong spans AND 36% missing files;
        # only the first half is caught by default).
        "checked_new": current is not None,
    }


def format_report(report: dict, root: str | Path) -> str:
    """Human-readable rendering of `stale_report`."""
    if not report["has_metadata"]:
        return (
            f"{root}: index carries no file metadata (built before staleness "
            f"tracking) — spans cannot be verified; re-index to enable checking"
        )
    if report["ok"]:
        msg = f"{root}: up to date ({report['indexed_count']} files verified)"
        if not report.get("checked_new"):
            # A verdict that names what it did not check is not misleading; a bare
            # "up to date" is. New files are invisible without --check-new.
            msg += "; new files not checked — re-run with --check-new"
        return msg

    lines = [
        f"{root}: STALE — "
        f"{len(report['changed'])} changed, {len(report['missing'])} missing, "
        f"{len(report['added'])} new (of {report['indexed_count']} indexed)"
    ]
    for rel in report["changed"]:
        lines.append(f"  changed  {rel}")
    for rel in report["missing"]:
        lines.append(f"  missing  {rel}")
    for rel in report["added"]:
        lines.append(f"  new      {rel}")
    lines.append("re-index to refresh: spindlebox index")
    return "\n".join(lines)
