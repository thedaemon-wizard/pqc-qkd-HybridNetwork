"""The published measurement reports carry counts, classes and times only.

`docs/measurements/` holds the output of `scripts/ppk_race_report.py` for the
before/after measurement of checklist row 2.17. The script promises not to
print a key_id, credential, identity or address, but the files are published
beside the tree, and the `--json` outputs are compressed, so the publication
test's text checks do not see inside them. This test decompresses every
`.json.gz`, reads every `.txt`, and refuses the shapes an identifier would
have: a UUID (arnika's key_ids), an IPv4 address, an e-mail-like `user@host`
(strongSwan identities) and a `psk=` assignment. It also holds each folder's
`SHA256SUMS` and `README.md` to the files actually present, so a re-run that
replaces a report cannot leave a stale checksum or an unexplained file.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MEASUREMENTS = ROOT / "docs" / "measurements"
FOLDERS = sorted(p for p in MEASUREMENTS.iterdir() if p.is_dir()) if MEASUREMENTS.is_dir() else []
REPORT_SUFFIXES = (".txt", ".json.gz")

IDENTIFIERS = {
    "uuid": re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I),
    "ipv4": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    "user@host": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+"),
    "psk=": re.compile(r"psk=", re.I),
}


def _reports(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.name.endswith(REPORT_SUFFIXES))


def _text(path: Path) -> str:
    raw = path.read_bytes()
    if path.name.endswith(".gz"):
        raw = gzip.decompress(raw)
    return raw.decode("utf-8")


def test_there_is_a_measurement_folder():
    assert FOLDERS, "docs/measurements/ has no measurement folder"


@pytest.mark.parametrize("folder", FOLDERS, ids=lambda p: p.name)
def test_every_report_is_free_of_identifiers(folder):
    for report in _reports(folder):
        text = _text(report)
        for name, pattern in IDENTIFIERS.items():
            hit = pattern.search(text)
            assert hit is None, f"{report.relative_to(ROOT)}: looks like a {name}: {hit.group(0)!r}"


@pytest.mark.parametrize("folder", FOLDERS, ids=lambda p: p.name)
def test_every_json_report_parses(folder):
    for report in _reports(folder):
        if report.name.endswith(".json.gz"):
            json.loads(_text(report))


@pytest.mark.parametrize("folder", FOLDERS, ids=lambda p: p.name)
def test_sha256sums_lists_exactly_the_reports(folder):
    listed = {}
    for line in (folder / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split(maxsplit=1)
        listed[name.strip()] = digest
    present = {p.name for p in _reports(folder)}
    assert set(listed) == present, f"{folder.name}: SHA256SUMS lists {sorted(set(listed) ^ present)} wrongly"
    for name, digest in listed.items():
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest, f"{folder.name}/{name}: checksum differs"


@pytest.mark.parametrize("folder", FOLDERS, ids=lambda p: p.name)
def test_the_readme_explains_every_report(folder):
    readme = (folder / "README.md").read_text(encoding="utf-8")
    for report in _reports(folder):
        stem = report.name.removesuffix(".json.gz").removesuffix(".txt")
        assert stem in readme, f"{folder.name}/README.md does not mention {stem}"
