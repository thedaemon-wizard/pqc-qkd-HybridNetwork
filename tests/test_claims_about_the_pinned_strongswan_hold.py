"""Claims about the pinned strongSwan tree must be derived from it, not typed.

`docs/vici-ppk.md` asserted that `notify_payload.h` "defines only
`USE_PPK = 16435`, `PPK_IDENTITY = 16436` and `NO_PPK_AUTH = 16437`". The header
also defines::

    INTERMEDIATE_EXCHANGE_SUPPORTED = 16438
    ADDITIONAL_KEY_EXCHANGE         = 16441
    USE_AGGFRAG                     = 16442
    SA_RESOURCE_INFO                = 16444

so the sentence was false, and `docs/references.md` repeated it. Dropping 16444
also discarded the strongest part of the argument: it is the HIGHEST Status Type
in the enum, which is what makes "16445 and 16446 are the two values immediately
above the top of the range" a much better observation than "they are absent".

The claim was written once and never re-derived. This file derives it.
"""
from __future__ import annotations

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
HEADER = (REPO / "submodules" / "strongswan" / "src" / "libcharon" / "encoding"
          / "payloads" / "notify_payload.h")

# Status Types occupy 16384-40959 in the IKEv2 registry; the Error Types sit
# below. The claim is about the top of the Status Type range.
_ENTRY = re.compile(r"^\s*([A-Z][A-Z0-9_]*)\s*=\s*(\d+)\s*,", re.M)


def _status_types() -> dict[str, int]:
    if not HEADER.exists():
        pytest.skip("strongswan submodule not checked out")
    src = HEADER.read_text(encoding="utf-8", errors="replace")
    return {name: int(val) for name, val in _ENTRY.findall(src)
            if 16384 <= int(val) < 24576}


def test_the_ppk_notifies_rfc_9867_needs_are_absent():
    """The load-bearing half of the claim."""
    names = set(_status_types())
    assert "USE_PPK_INT" not in names
    assert "PPK_IDENTITY_KEY" not in names


def test_16444_is_the_highest_status_type():
    """What makes "immediately above the top of the range" true.

    If a later strongSwan adds a Status Type above 16444, the sentence in
    docs/vici-ppk.md stops being the sharp observation it is and becomes a
    weaker one. Better to be told than to keep asserting it.
    """
    st = _status_types()
    top = max(st.values())
    assert top == 16444, (
        f"the highest Status Type is now {top} "
        f"({[k for k, v in st.items() if v == top]}), not 16444 -- the "
        f"'16445/16446 sit immediately above the top' wording in "
        f"docs/vici-ppk.md and docs/references.md needs re-deriving")


def test_the_ppk_trio_is_present_and_numbered_as_documented():
    st = _status_types()
    assert st.get("USE_PPK") == 16435
    assert st.get("PPK_IDENTITY") == 16436
    assert st.get("NO_PPK_AUTH") == 16437


def test_no_document_claims_the_header_defines_only_the_trio():
    """The exact false sentence, in every file that carried it."""
    offenders = []
    for f in list((REPO / "docs").rglob("*.md")) + [REPO / "README.md",
                                                    REPO / "ARCHITECTURE.md"]:
        if not f.exists():
            continue
        txt = f.read_text(encoding="utf-8", errors="replace")
        lines = txt.splitlines()
        for n, line in enumerate(lines, 1):
            low = line.lower()
            if "16435" not in line:
                continue
            if "only" not in low or "16438" in line:
                continue
            # Quoting the false sentence in order to retract it is the record
            # of why the wording changed and must survive. Look at a +/-4 line
            # window for the retraction, because a bare substring search flags
            # the correction itself -- which is exactly what happened here.
            window = "\n".join(lines[max(0, n - 5):n + 4]).lower()
            if any(w in window for w in ("previous wording", "is false",
                                         "was false", "used to say",
                                         "earlier version")):
                continue
            offenders.append(f"{f.relative_to(REPO)}:{n}")
    assert offenders == [], (
        "these say the header defines ONLY the PPK trio, which is false -- it "
        f"also defines 16438, 16441, 16442 and 16444: {offenders}")


def test_the_four_other_notifies_really_are_there():
    """Not vacuous: the four the claim omitted must exist."""
    st = _status_types()
    for name, val in [("INTERMEDIATE_EXCHANGE_SUPPORTED", 16438),
                      ("ADDITIONAL_KEY_EXCHANGE", 16441),
                      ("USE_AGGFRAG", 16442),
                      ("SA_RESOURCE_INFO", 16444)]:
        assert st.get(name) == val, f"{name} is not {val} in the pinned header"


# --------------------------------------------------------------------------
# The pointer docs/references.md makes must land somewhere.
# --------------------------------------------------------------------------

def test_the_sp_800_227_note_is_where_references_says_it_is():
    """`references.md` pointed at vici-ppk.md for a note that lived elsewhere.

    tests/test_referenced_paths_exist.py could not catch it: the FILE exists,
    it just did not contain the section promised. A link that resolves to the
    wrong content is not a working link.
    """
    refs = (REPO / "docs" / "references.md").read_text(encoding="utf-8")
    vici = (REPO / "docs" / "vici-ppk.md").read_text(encoding="utf-8")
    assert "800-227" in refs, "the row that makes the promise is gone"
    assert "vici-ppk.md" in refs
    assert "800-227" in vici, (
        "docs/references.md points at vici-ppk.md for the SP 800-227 combiner "
        "analysis, and vici-ppk.md does not mention it")
    assert "FixedInfo" in vici


def test_the_salt_claim_matches_what_arnika_actually_passes():
    """A nil HKDF salt is the approved default, not a missing salt."""
    kdf = REPO / "submodules" / "arnika" / "kdf" / "kdf.go"
    if not kdf.exists():
        pytest.skip("arnika submodule not checked out")
    src = kdf.read_text(encoding="utf-8")
    assert "hkdf.New(sha3.New256, combined, nil, nil)" in src, (
        "the KDF call changed; re-derive the SP 800-227 analysis in "
        "docs/vici-ppk.md rather than leaving it asserting the old shape")

    vici = (REPO / "docs" / "vici-ppk.md").read_text(encoding="utf-8")
    assert "neither salt nor FixedInfo" not in vici, (
        "the analysis says arnika supplies neither salt nor FixedInfo. RFC 5869 "
        "2.2 defines a nil HKDF salt as HashLen zero bytes, which is the "
        "default salt SP 800-56C permits -- only FixedInfo is genuinely absent")
