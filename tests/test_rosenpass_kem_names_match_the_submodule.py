"""What we say Rosenpass uses must be what the pinned Rosenpass says it uses.

Six tracked files described the Rosenpass handshake as ML-KEM-768, including
two pages of the public demo (`/` and `/keyflow`) and the README's own
architecture table. The pinned submodule disagrees, and it disagrees in the one
place that cannot drift from the implementation -- its domain-separation label,
which is mixed into the protocol transcript:

    rosenpass/src/labeled_prf.rs
    PrfTree::zero().mix("Rosenpass v1 mceliece460896 Kyber512 ChaChaPoly1305 BLAKE2s")

Classic McEliece 460896 as the static KEM and Kyber512 as the ephemeral one.
Kyber512 is pre-standardisation Kyber, not FIPS 203 ML-KEM -- liboqs ships them
as separate algorithms with different sizes. There is no ML-KEM anywhere in the
Rosenpass tree.

Why it mattered enough to guard:

  * The claim was about to be shown to the arnika maintainers, who know the
    Rosenpass authors. A screenshot captioned "Rosenpass PQC handshake
    (ML-KEM-768)" is the kind of error that costs credibility disproportionately.
  * It changes a NIST argument. SP 800-227 Sec. 4.6.2's combiner (14) requires
    at least one input "generated from ... an approved KEM"; whether the PQC
    half qualifies decides whether HKDF(QKD || PQC) sits inside an approved
    construction. Kyber512 is not an approved KEM; ML-KEM-768 would be.
  * The IPsec lane's `KE1_ML_KEM_768` IS real FIPS 203 -- but that is the IKE
    key exchange, not arnika's HKDF input. The two are easy to conflate and the
    documents did exactly that.

The label is derived here rather than hardcoded, so bumping the submodule to a
Rosenpass that really does use ML-KEM updates the expectation automatically.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LABEL_FILE = ROOT / "submodules" / "rosenpass" / "rosenpass" / "src" / "labeled_prf.rs"
LABEL = re.compile(r'"Rosenpass v1 ([^"]+)"')

# Text that pairs Rosenpass with ML-KEM within a short window, in either order.
CONFLATION = re.compile(
    r"Rosenpass[^.\n|]{0,70}ML[-_]KEM|ML[-_]KEM[^.\n|]{0,40}(?:via\s+)?Rosenpass",
    re.IGNORECASE,
)

# Files allowed to contain the pairing because they exist to correct it.
DOCUMENTS_THE_CORRECTION = {
    "tests/test_rosenpass_kem_names_match_the_submodule.py",
    "docs/paper_mapping.md",
    "docs/IMAGE1_VPN_SCOPE.md",
    "services/webui-frontend/src/pages/KeyFlow.tsx",
    "VERIFICATION_CHECKLIST.md",
}
SKIP_SUFFIXES = {".pdf", ".png", ".jpg", ".gif", ".webm", ".ico", ".woff2"}


def _suite() -> str:
    if not LABEL_FILE.is_file():
        pytest.skip("rosenpass submodule not checked out")
    m = LABEL.search(LABEL_FILE.read_text(encoding="utf-8"))
    if not m:
        pytest.fail(
            f"no 'Rosenpass v1 ...' domain-separation label in {LABEL_FILE.name}. "
            "Upstream changed the label format; re-derive the KEM names before "
            "trusting anything this file asserts."
        )
    return m.group(1)


def test_the_pinned_rosenpass_does_not_use_ml_kem():
    """Derive the suite from the label, and pin what it actually names."""
    suite = _suite()
    lowered = suite.lower()
    assert "ml-kem" not in lowered and "ml_kem" not in lowered, (
        f"the pinned Rosenpass label now names ML-KEM ({suite!r}). If upstream "
        "really did move to FIPS 203, this guard and the six documents it "
        "protects should be updated together -- that is the point of deriving "
        "the name here instead of hardcoding it."
    )
    assert "mceliece" in lowered, f"expected Classic McEliece in the suite, got {suite!r}"
    assert "kyber" in lowered, f"expected Kyber in the suite, got {suite!r}"


def test_no_tracked_file_calls_the_rosenpass_handshake_ml_kem():
    """The claim that was on two live demo pages and in the README.

    Runs even when the submodule is absent: it is a text check over this
    repository, and the whole failure mode was text that nothing executed.
    """
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()

    offenders: list[str] = []
    for rel in tracked:
        path = ROOT / rel
        if not path.is_file() or path.suffix in SKIP_SUFFIXES:
            continue
        if rel in DOCUMENTS_THE_CORRECTION:
            continue
        try:
            body = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line_no, line in enumerate(body.splitlines(), 1):
            if CONFLATION.search(line):
                offenders.append(f"{rel}:{line_no}: {line.strip()[:110]}")

    assert not offenders, (
        "these describe the Rosenpass handshake as ML-KEM. The pinned Rosenpass "
        "uses Classic McEliece 460896 + Kyber512 -- see its own domain-separation "
        "label in rosenpass/src/labeled_prf.rs. The IPsec lane's KE1_ML_KEM_768 is "
        "real FIPS 203, but that is the IKE key exchange, not arnika's HKDF "
        "input:\n  " + "\n  ".join(offenders)
    )
