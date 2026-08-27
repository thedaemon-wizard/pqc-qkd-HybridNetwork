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
That derivation needs the submodule on disk, and CI's `python` job checks out
without submodules by default -- so it inits `submodules/rosenpass` explicitly
before running pytest, and `_suite()` below fails rather than skips when the
file is missing under CI. Without both, the derived half would go quiet and
only the text scan would still gate.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LABEL_FILE = ROOT / "submodules" / "rosenpass" / "rosenpass" / "src" / "labeled_prf.rs"
LABEL = re.compile(r'"Rosenpass v1 ([^"]+)"')

# Text that pairs Rosenpass with ML-KEM within a short window, in either order.
#
# The window deliberately spans NEWLINES. The first version of this pattern
# excluded them (`[^.\n|]`) and ran per line, and it missed a seventh instance:
# the sidebar in services/webui-frontend/src/App.tsx, which renders on all 13
# pages and read
#
#     ML-KEM-768 + HKDF-SHA3-256<br />
#     arnika · liboqs · rosenpass
#
# as one visual block. Two facts on adjacent lines make a claim that neither
# line makes alone, and a line-oriented scan cannot see it. Same failure shape
# as grepping SP 800-227 for "quantum key distribution" and missing it because
# the PDF hyphenated it across a line break as "quan-\ntum".
#
# `.` stays excluded so the window cannot run past a sentence boundary, which
# is what keeps a 70-character reach from pairing unrelated prose.
CONFLATION = re.compile(
    r"Rosenpass[^.|]{0,70}ML[-_]KEM|ML[-_]KEM[^.|]{0,70}Rosenpass",
    re.IGNORECASE,
)

# Adjacency is only a defect when the ML-KEM is UNATTRIBUTED. The corrected
# sidebar lists
#
#     IKEv2: ML-KEM-768 (RFC 9370)
#     Rosenpass: McEliece + Kyber512
#
# on consecutive lines, which the window above matches -- yet it is exactly
# right, because each algorithm names the lane that uses it. What made the old
# text wrong was that "ML-KEM-768 + HKDF-SHA3-256" belonged to nothing in
# particular and the eye attached it to the components underneath. So a match
# carrying an explicit owner for the ML-KEM is not a finding.
ATTRIBUTED = re.compile(r"IKEv2|IKE_SA|RFC\s*9370|KE1_ML_KEM|key exchange", re.IGNORECASE)

# Prose files allowed to contain the pairing because they exist to correct it.
# Source files are NOT listed here: their comments are stripped instead, so the
# code itself stays under the guard. Exempting a whole source file would make
# the exemption permanent -- the explanatory comment would keep satisfying the
# anchor check forever, and a real regression in the JSX beside it would pass.
DOCUMENTS_THE_CORRECTION = {
    "tests/test_rosenpass_kem_names_match_the_submodule.py",
    "docs/paper_mapping.md",
    "docs/IMAGE1_VPN_SCOPE.md",
    "VERIFICATION_CHECKLIST.md",
}
SKIP_SUFFIXES = {".pdf", ".png", ".jpg", ".gif", ".webm", ".ico", ".woff2"}

BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
LINE_COMMENT = re.compile(r"(?<!:)//[^\n]*")


def _strip_comments(body: str, suffix: str) -> str:
    """Remove comments from source, so an explanation is not read as a claim.

    Every file corrected here carries a comment saying what the mistake was,
    and those comments necessarily pair "Rosenpass" with "ML-KEM". Stripping
    them keeps the file under the guard instead of exempting it wholesale.
    `(?<!:)` keeps `https://` out of the line-comment pattern.
    """
    if suffix not in {".ts", ".tsx", ".js", ".jsx"}:
        return body
    return LINE_COMMENT.sub("", BLOCK_COMMENT.sub("", body))


def _suite() -> str:
    if not LABEL_FILE.is_file():
        if os.environ.get("CI"):
            pytest.fail(
                f"{LABEL_FILE} is absent under CI, so the half of this guard that "
                "derives the KEM names from the pinned submodule did not run. "
                "Restore the `git submodule update --init --depth 1 "
                "submodules/rosenpass` step in the `python` job rather than "
                "letting this degrade to a skip."
            )
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
        try:
            body = _strip_comments(path.read_text(encoding="utf-8"), path.suffix)
        except (UnicodeDecodeError, OSError):
            continue

        if rel in DOCUMENTS_THE_CORRECTION:
            # Exempt because it explains the mistake, so it has to name it.
            # Require it to also name the right answer, or the exemption
            # becomes the place a wrong claim hides.
            if CONFLATION.search(body):
                assert re.search(r"McEliece|Kyber512", body, re.IGNORECASE), (
                    f"{rel} is exempt because it documents the correction, but it "
                    "pairs Rosenpass with ML-KEM without naming the actual suite."
                )
            continue

        # Scan the WHOLE body, not line by line: the seventh instance was two
        # adjacent lines in a sidebar, which no per-line scan can see.
        for m in CONFLATION.finditer(body):
            if ATTRIBUTED.search(m.group(0)):
                continue
            line_no = body.count("\n", 0, m.start()) + 1
            snippet = " ".join(m.group(0).split())[:110]
            offenders.append(f"{rel}:{line_no}: {snippet}")

    assert not offenders, (
        "these describe the Rosenpass handshake as ML-KEM. The pinned Rosenpass "
        "uses Classic McEliece 460896 + Kyber512 -- see its own domain-separation "
        "label in rosenpass/src/labeled_prf.rs. The IPsec lane's KE1_ML_KEM_768 is "
        "real FIPS 203, but that is the IKE key exchange, not arnika's HKDF "
        "input:\n  " + "\n  ".join(offenders)
    )
