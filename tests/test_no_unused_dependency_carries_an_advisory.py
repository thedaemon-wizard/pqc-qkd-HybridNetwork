"""A dependency nothing uses is pure attack surface.

Two packages were pinned, imported by nothing, required by nothing, and
carrying six HIGH advisories between them:

    services/webui-backend/requirements.txt   cryptography==44.0.0
        GHSA-g6cj-pr64-35w5  PKCS#7 Bleichenbacher oracle  (patched 50.0.0)
        GHSA-jwv3-5hgf-82ww                                (patched 49.0.0)
        GHSA-537c-gmf6-5ccf  vulnerable OpenSSL in wheels  (patched 48.0.1)
        GHSA-r6ph-v2qm-q3c2                                (patched 46.0.5)

    services/bb84-kme/requirements.txt        python-multipart==0.0.20
        GHSA-5rvq-cxj2-64vf  DoS
        GHSA-pp6c-gr5w-3c5g  DoS

Removing beat bumping. A six-major upgrade of a package nothing calls is risk
with no benefit, and removal retires the advisories rather than chasing them.

Verified before removal, not assumed:
  * no source file imports `cryptography`
  * no route takes a multipart body -- no `UploadFile`, no `Form(`
  * the published metadata of fastapi, uvicorn, httpx, pydantic, docker and
    websockets declares neither
  * FastAPI needs python-multipart only under its `standard` / `all` extras,
    and bb84-kme installs plain `fastapi==0.115.6`

CI proves the services still start: "Container images build" and "ETSI GS QKD
014 contract tests (live KMEs)" run the real containers, so a package that was
actually needed would fail there rather than here.
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[1]
BACKEND_REQ = REPO / "services" / "webui-backend" / "requirements.txt"
KME_REQ = REPO / "services" / "bb84-kme" / "requirements.txt"


def _pins(path: pathlib.Path) -> set[str]:
    """Package names actually being installed -- comments do not count."""
    names = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        m = re.match(r"^([A-Za-z0-9_.\-]+)", line)
        if m:
            names.add(m.group(1).lower())
    return names


def test_cryptography_is_not_installed_where_nothing_imports_it():
    assert "cryptography" not in _pins(BACKEND_REQ), (
        "cryptography is pinned in webui-backend again. Nothing imports it and "
        "no other requirement declares it; if that has changed, say what needs "
        "it in the file and pin a version past GHSA-g6cj-pr64-35w5 (50.0.0)")


def test_python_multipart_is_not_installed_where_no_route_parses_one():
    assert "python-multipart" not in _pins(KME_REQ), (
        "python-multipart is pinned in bb84-kme again. No route takes a "
        "multipart body and fastapi needs it only under the `standard` extra")


def test_nothing_imports_cryptography():
    """The premise. If this fails, the removal was wrong and must be undone."""
    hits = []
    for f in (REPO / "services").rglob("*.py"):
        if any(p.startswith(".") for p in f.parts):
            continue
        if re.search(r"^\s*(from|import)\s+cryptography\b",
                     f.read_text(encoding="utf-8", errors="replace"), re.M):
            hits.append(str(f.relative_to(REPO)))
    assert hits == [], (
        f"{hits} import cryptography, but it was removed from requirements -- "
        f"the service will fail at import")


def test_no_route_accepts_a_multipart_body():
    """Same, for the other removal."""
    hits = []
    for f in (REPO / "services" / "bb84-kme").rglob("*.py"):
        txt = f.read_text(encoding="utf-8", errors="replace")
        if re.search(r"\bUploadFile\b|=\s*File\(|:\s*UploadFile|=\s*Form\(", txt):
            hits.append(str(f.relative_to(REPO)))
    assert hits == [], (
        f"{hits} accept form or file uploads, which needs python-multipart")


def test_the_removals_are_documented_where_they_happened():
    """A silent deletion invites a silent restoration."""
    for path, pkg, ghsa in ((BACKEND_REQ, "cryptography", "GHSA-g6cj-pr64-35w5"),
                            (KME_REQ, "python-multipart", "GHSA-5rvq-cxj2-64vf")):
        txt = path.read_text(encoding="utf-8")
        assert pkg in txt, f"{path.name} no longer explains why {pkg} went"
        assert ghsa in txt, f"{path.name} does not record the advisory"
        assert "REMOVED" in txt
