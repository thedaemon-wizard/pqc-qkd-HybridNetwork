"""The release version is written in several places and must be one number.

A release of this repository states its version in:

  * CITATION.cff, what a citation of the software names;
  * services/webui-frontend/package.json, the only package manifest in the tree,
    and its lockfile, which `npm ci` installs from;
  * the newest heading of CHANGELOG.md, what a reader of the release notes sees.

Nothing ties them together at build time, so each release is a chance for one
of them to be left behind -- and a citation that names a version the changelog
never mentions sends the reader to a release that does not exist. The previous
release is tagged v0.1.0; the one that moves the arnika pin to upstream PR #51's
head is 0.2.0. This file does not restate the number: it holds the places to
each other, so the next release only has to change it where it is written.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CITATION = ROOT / "CITATION.cff"
CHANGELOG = ROOT / "CHANGELOG.md"
PACKAGE = ROOT / "services" / "webui-frontend" / "package.json"
LOCKFILE = ROOT / "services" / "webui-frontend" / "package-lock.json"

_SEMVER = r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?"
# `## [0.2.0] - 2026-09-26`, `## 0.2.0 (2026-09-26)`, `## v0.2.0`: the heading
# forms Keep a Changelog and its variants use. `## [Unreleased]` is skipped.
_HEADING = re.compile(
    rf"^##\s+\[?v?(?P<version>{_SEMVER})\]?(?:\s*(?:[-–—]\s*|\()(?P<date>\d{{4}}-\d{{2}}-\d{{2}})\)?)?",
    re.M)


def _releases() -> list[tuple[str, str | None]]:
    text = CHANGELOG.read_text(encoding="utf-8")
    return [(m.group("version"), m.group("date")) for m in _HEADING.finditer(text)]


def _key(version: str) -> tuple:
    core, _, pre = version.partition("-")
    # A pre-release sorts before its release (semver section 11).
    return (*map(int, core.split(".")), pre == "", pre)


def _citation() -> dict:
    return yaml.safe_load(CITATION.read_text(encoding="utf-8"))


def test_the_changelog_has_releases_newest_first():
    releases = _releases()
    assert releases, "CHANGELOG.md has no `## <version>` heading"
    versions = [v for v, _ in releases]
    assert versions == sorted(versions, key=_key, reverse=True), (
        f"CHANGELOG.md headings are not newest first: {versions}")
    assert len(set(versions)) == len(versions), f"a version is listed twice: {versions}"


def test_the_citation_is_a_citation_file():
    cff = _citation()
    for field in ("cff-version", "message", "title", "authors", "version"):
        assert cff.get(field), f"CITATION.cff has no {field}"
    assert isinstance(cff["version"], str), (
        f"CITATION.cff version is the YAML {type(cff['version']).__name__} "
        f"{cff['version']!r}; quote it")


def test_citation_package_and_changelog_name_one_version():
    newest = _releases()[0][0]
    package = json.loads(PACKAGE.read_text(encoding="utf-8"))["version"]
    cited = _citation()["version"]
    assert cited == package == newest, (
        f"CITATION.cff says {cited}, package.json {package}, and the newest "
        f"CHANGELOG.md heading {newest}")


def test_the_lockfile_was_regenerated_with_the_manifest():
    """`npm install --package-lock-only` writes the version into both places."""
    lock = json.loads(LOCKFILE.read_text(encoding="utf-8"))
    package = json.loads(PACKAGE.read_text(encoding="utf-8"))["version"]
    assert lock.get("version") == package, f"package-lock.json {lock.get('version')} vs {package}"
    assert lock["packages"][""].get("version") == package


def test_a_dated_release_is_dated_the_same_in_the_citation():
    newest, date = _releases()[0]
    released = _citation().get("date-released")
    if date is None or released is None:
        # Only a contradiction is a defect; a date stated in one place is not.
        return
    assert str(released) == date, (
        f"CHANGELOG.md dates {newest} {date}, CITATION.cff says {released}")
