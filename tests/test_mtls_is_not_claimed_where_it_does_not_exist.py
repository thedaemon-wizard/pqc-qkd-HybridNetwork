"""The docs advertised mTLS while the UI, in the same build, denied it.

`services/webui-frontend/src/pages/HIL.tsx` tells a visitor, on screen:

    mTLS is not implemented. This step used to say to set
    ETSI_MTLS_ENABLED=true; no code has ever read that variable.

Meanwhile `README.md` drew "HTTP (mTLS opt.)" in its architecture figure and
told Quickstart readers that `make init` "generates mTLS certs", and
`ARCHITECTURE.md` described the ETSI 014 client as "HTTP/mTLS". Which one a
reader believed depended on whether they opened the README or the page.

The measurable half: nothing consumes the certificates. A grep for `pki/`
across every compose file and every Dockerfile returns zero hits, and no TLS
keyfile/certfile argument appears in the KME. So the lane is not merely
unfinished -- it has no wiring at all.

WHY THE Makefile CHANGED TOO. `make init` ran `./pki/gen-certs.sh`
unconditionally, so every clone wrote a 4096-bit CA key plus four keypairs
into the working tree for that non-existent lane. Generating unused private
key material is not neutral in a repository whose own release gates scan for
committed secrets: it puts real keys on disk for no benefit, and `pki/` is one
`git add -A` away from being tracked. The script still exists behind
`make pki` for whoever builds the lane.

This file is deliberately two-sided. It fails if the docs claim mTLS works,
AND it fails if someone "fixes" the contradiction by deleting the honest
disclosure instead.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

README = ROOT / "README.md"
ARCHITECTURE = ROOT / "ARCHITECTURE.md"
MAKEFILE = ROOT / "Makefile"
HIL = ROOT / "services" / "webui-frontend" / "src" / "pages" / "HIL.tsx"
GEN_CERTS = ROOT / "pki" / "gen-certs.sh"


def _read(p: Path) -> str:
    assert p.is_file(), f"{p.relative_to(ROOT)} is missing"
    return p.read_text(encoding="utf-8")


class TestNothingConsumesTheCertificates:
    """The premise, measured rather than asserted."""

    def test_no_compose_service_or_image_mounts_pki(self) -> None:
        hits = []
        globs = ["docker-compose*.yml", "deploy/*.yml", "nodes/*/Dockerfile",
                 "services/*/Dockerfile*"]
        for g in globs:
            for f in ROOT.glob(g):
                for n, line in enumerate(_read(f).splitlines(), 1):
                    # `/etc/ssl/private/` is OpenSSL's own path in the TLS demo
                    # images and has nothing to do with this repository's pki/.
                    if re.search(r"(?<!ssl/)\bpki/", line):
                        hits.append(f"{f.relative_to(ROOT)}:{n}: {line.strip()}")
        assert not hits, (
            "something now consumes pki/ -- the mTLS lane may be real, so the "
            "documentation corrections this file pins need revisiting:\n  "
            + "\n  ".join(hits)
        )

    def test_the_kme_configures_no_tls(self) -> None:
        src = _read(ROOT / "services" / "bb84-kme" / "app" / "main.py")
        for arg in ("ssl_certfile", "ssl_keyfile", "ssl_ca_certs"):
            assert arg not in src, f"{arg} appears in the KME; mTLS may now exist"

    def test_the_generator_still_exists(self) -> None:
        # The fix is "do not run it by default", not "delete the lane".
        assert GEN_CERTS.is_file()


class TestTheDocsDoNotClaimItWorks:

    CLAIMS_IT_WORKS = re.compile(
        r"HTTP/mTLS|mTLS opt\.|generates mTLS certs", re.I)

    @pytest.mark.parametrize("path", [README, ARCHITECTURE],
                             ids=lambda p: p.name)
    def test_no_document_advertises_mtls(self, path: Path) -> None:
        offending = [
            ln.strip() for ln in _read(path).splitlines()
            if self.CLAIMS_IT_WORKS.search(ln)
        ]
        assert not offending, (
            f"{path.relative_to(ROOT)} advertises mTLS that is not wired:\n  "
            + "\n  ".join(offending)
        )

    def test_the_detector_would_catch_the_old_wording(self) -> None:
        # Guards against the parametrised test passing because the regex is
        # broken rather than because the docs are clean.
        for old in ("│ HTTP (mTLS opt.) │",
                    "# 2) Initialise: ... generates mTLS certs",
                    "- ETSI 014 client (HTTP/mTLS)"):
            assert self.CLAIMS_IT_WORKS.search(old), f"detector missed: {old}"

    def test_the_disclosure_is_still_on_screen(self) -> None:
        # The other direction: do not resolve the contradiction by deleting the
        # sentence that was telling the truth.
        assert "mTLS is not implemented" in _read(HIL)

    def test_the_docs_say_so_too(self) -> None:
        both = _read(README) + _read(ARCHITECTURE)
        assert re.search(r"mTLS (?:NOT|not) implemented", both), (
            "neither README nor ARCHITECTURE states that mTLS is absent; a "
            "reader now learns it only by opening /hil"
        )


class TestInitDoesNotGenerateKeysNobodyUses:

    def test_make_init_does_not_run_the_generator(self) -> None:
        text = _read(MAKEFILE)
        m = re.search(r"^init:.*?(?=^\S|\Z)", text, re.M | re.S)
        assert m, "the init target is gone or was renamed"
        assert "gen-certs.sh" not in m.group(0), (
            "make init generates a CA key and four keypairs for a lane that "
            "nothing consumes"
        )

    def test_the_generator_is_still_reachable(self) -> None:
        text = _read(MAKEFILE)
        m = re.search(r"^pki:.*?(?=^\S|\Z)", text, re.M | re.S)
        assert m, "no `make pki` target; the lane is now unbuildable"
        assert "gen-certs.sh" in m.group(0)

    def test_generated_keys_could_not_be_committed_anyway(self) -> None:
        # Belt and braces: even run by hand, the output must be ignored.
        for name in ("pki/ca.key", "pki/server-alice.key", "pki/client-bob.key"):
            r = subprocess.run(["git", "check-ignore", name],
                               cwd=ROOT, capture_output=True, text=True)
            assert r.returncode == 0, (
                f"{name} is NOT gitignored -- running `make pki` would leave a "
                f"private key one `git add -A` away from being tracked"
            )
