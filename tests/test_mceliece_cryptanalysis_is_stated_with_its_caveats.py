"""Cost figures against a shipped primitive may not outlive their conditions.

WHY THIS FILE EXISTS. `docs/threat-model.md` section 4.1 records the
August-September 2026 preprint line against Classic McEliece, whose 460896
parameter set is the static KEM in the pinned Rosenpass. The numbers in that
section are the kind that get quoted onward: "$2^{145.22}$ for mceliece460896"
reads like a break, and it is not one. Each figure is conditional on something
the authors state plainly and a summariser drops first:

  - Weis: "None of the Classic McEliece computations is close to practical, and
    several ingredients are heuristic."
  - Saarinen: the model "excludes address generation and memory traffic and uses
    budget estimates for some stages".
  - Both demonstrations are on toy challenge instances (m=8), not on any NIST
    parameter set.
  - Apon's lower bound is aimed at the Vedenev route specifically. Citing it as a
    refutation of the whole line is the same error in the opposite direction.

This file fails if a figure survives an edit that removed its condition.

WHAT IT DOES NOT DO. It does not check the arithmetic, and it does not pin the
numbers themselves -- revisions change them (ePrint 2026/1786 is on its seventh).
It pins the pairing: if the section still carries cost exponents, it must still
carry the four qualifiers above.

A NOTE ON THE NEGATIVE ASSERTIONS. They are anchored on phrases that would only
appear if the section had been rewritten into a claim of a break. Writing them as
bare substring bans would make this file match its own docstring, which is the
trap this suite has hit repeatedly -- so each is scoped to the section text that
was actually read from the document.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
THREAT_MODEL = ROOT / "docs" / "threat-model.md"
REFERENCES = ROOT / "docs" / "references.md"

# The heading that opens the section, and the next same-or-higher heading.
_SECTION_START = "### 4.1 The code-based half is under active analysis"


def _section() -> str:
    text = THREAT_MODEL.read_text(encoding="utf-8")
    start = text.find(_SECTION_START)
    assert start != -1, (
        "docs/threat-model.md no longer has section 4.1. If the cryptanalysis "
        "record moved, move this test with it rather than deleting it -- the "
        "point is that the numbers do not travel without their conditions."
    )
    rest = text[start + len(_SECTION_START):]
    end = re.search(r"^#{1,3} ", rest, re.M)
    return rest[: end.start()] if end else rest


def test_the_section_still_carries_cost_exponents():
    """Guard the guard: if the figures were removed, the rest is vacuous."""
    body = _section()
    assert re.search(r"2\^\{?1[0-9]{2}", body) or "2^{145.22}" in body, (
        "section 4.1 no longer contains any cost exponent, so the assertions "
        "below would pass while checking nothing"
    )


@pytest.mark.parametrize(
    "phrase,why",
    [
        (
            "close to practical",
            "Weis's own qualifier is what stops the figures reading as a break",
        ),
        (
            "heuristic",
            "the estimates are conditional on assumptions the authors state",
        ),
        (
            "excludes address generation and memory traffic",
            "Saarinen's cost model exclusion; without it 2^145.22 looks absolute",
        ),
        (
            "Vedenev",
            "Apon's lower bound is scoped to that route, not to the whole line",
        ),
    ],
)
def test_each_condition_survives(phrase, why):
    body = _section()
    assert phrase in body, (
        f"section 4.1 lost the phrase {phrase!r}. {why}. Restore it, or remove "
        f"the figure it qualifies -- the pairing is the point, not the prose."
    )


def test_the_toy_instance_scope_is_stated():
    """The demonstrations are m=8 challenges, not NIST parameter sets."""
    body = _section()
    assert "toy" in body.lower() or "m=8" in body.replace("$", "").replace("`", ""), (
        "section 4.1 no longer says the demonstrations are on toy challenge "
        "instances. Without it a reader may take 'solved' as applying to "
        "mceliece460896, which no paper in the line claims."
    )


# Negators that flip the meaning of the banned phrases. The first version of
# this check was a bare substring ban and it fired on the section's own sentence
# "nothing in this deployment is broken" -- an honest negation reported as the
# overclaim it rules out. A ban that cannot tell "X is broken" from "X is not
# broken" is worse than no ban, because the fix it invites is to weaken the
# document. Scope the match to the clause instead.
_NEGATORS = ("nothing", "no ", "not ", "none", "neither", "never", "without")


def _has_affirmative(body: str, claim: str) -> bool:
    """True only where `claim` appears outside the reach of a negator."""
    for m in re.finditer(re.escape(claim), body):
        window = body[max(0, m.start() - 120): m.start()]
        # Look only after the last sentence boundary: a negation two sentences
        # back does not govern this clause.
        clause = re.split(r"[.;:]\s", window)[-1]
        if not any(n in clause for n in _NEGATORS):
            return True
    return False


@pytest.mark.parametrize(
    "claim", ["is broken", "has been broken", "practical attack exists"]
)
def test_the_section_does_not_claim_the_deployment_is_broken(claim):
    """No key has been recovered at any NIST size; the text must not imply one."""
    body = _section().lower()
    assert not _has_affirmative(body, claim), (
        f"section 4.1 asserts {claim!r} outside a negation. No paper in this "
        f"line recovers a key at a NIST parameter size, and Weis says so "
        f"explicitly in the abstract this section quotes."
    )


def test_the_negation_aware_check_still_detects_the_real_thing():
    """Guard the guard: the matcher must not have been softened into a no-op."""
    assert _has_affirmative("classic mceliece is broken today", "is broken")
    assert not _has_affirmative("nothing here is broken", "is broken")
    assert not _has_affirmative("no parameter set is broken", "is broken")
    # A negation in a PREVIOUS sentence must not license the claim.
    assert _has_affirmative("nothing failed. the kem is broken", "is broken")


def test_references_dates_the_bsi_endorsement_against_the_line():
    """BSI recommends the set, and its version predates the cryptanalysis.

    Quoting the endorsement without the date is the single most misleading thing
    this repository could do with it, because the recommendation is not a
    response to the attacks -- it was written seven months earlier.
    """
    text = REFERENCES.read_text(encoding="utf-8")
    assert "2026-01-23" in text, (
        "docs/references.md no longer dates TR-02102-1. The BSI endorsement of "
        "mceliece460896 predates the August 2026 cryptanalysis line and has not "
        "been revisited; the date is what makes that checkable."
    )
    assert "threat-model.md" in text, (
        "the BSI passage should point at where the conditions are set out, "
        "rather than restating figures that will drift"
    )
