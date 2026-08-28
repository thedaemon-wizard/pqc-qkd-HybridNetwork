"""TNO answering "no key" must not be reported as TNO being unavailable.

Found on the live demo while verifying the fix for the collapsing
`same_order_of_magnitude` bool -- the same inversion, one layer further down.

TNO signals a converged no-key result by RAISING, not by returning a number::

    submodules/tno-qkd-key-rate/.../quantum/bb84.py:593-595
        if rate < 0:
            error_msg = "Optimization resulted in a negative key rate."
            raise ValueError(error_msg)

`compute_tno_rate` tries the decoy estimate, catches any exception, and falls
back to the fully-asymptotic one. Past ~254 km BOTH raise, and the second raise
propagated to `main.py`'s `except Exception`, so the endpoint returned
`tno: null`. Measured through the public API at 254, 260, 270 and 300 km::

    verdict:  "engine_unavailable"
    error:    "Optimization resulted in a negative key rate."
    tno:      null
    ours:     0.0

The engine was installed, it ran, and it answered -- with exactly the same
answer as our closed form. The strongest agreement two independent
implementations can reach was reported as "the optimiser is not installed", by
a payload that was simultaneously quoting the optimiser's output in its own
error field.

Nothing could have caught it. `except Exception` is unremarkable, "the optional
engine is missing" is a plausible thing for a verification page to say, and the
default 10 km never reaches the case.
"""
from __future__ import annotations

import pathlib
import re
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "bb84-kme"))

from app.backends.tno_backend import _is_converged_no_key  # noqa: E402

TNO_SRC = (REPO / "submodules" / "tno-qkd-key-rate" / "src" / "tno" / "quantum"
           / "communication" / "qkd_key_rate" / "quantum")


# --------------------------------------------------------------------------
# The predicate.
# --------------------------------------------------------------------------

def test_a_converged_no_key_is_recognised():
    exc = ValueError("Optimization resulted in a negative key rate.")
    assert _is_converged_no_key(exc)


@pytest.mark.parametrize("exc", [
    ImportError("No module named 'tno'"),
    ModuleNotFoundError("No module named 'tno.quantum'"),
    RuntimeError("Optimization resulted in a negative key rate."),
    ValueError("detector efficiency must be in [0, 1]"),
    ValueError("could not convert string to float: 'abc'"),
    TypeError("optimize_rate() missing 1 required positional argument"),
    KeyError("mu"),
])
def test_everything_else_still_propagates(exc):
    """A genuine failure must keep reading as a failure.

    ValueError is also what bad input raises, which is why the type alone is
    not enough and the message is matched too. RuntimeError carrying the same
    text is rejected: if upstream ever changes the exception class, this should
    surface as a loud "engine_unavailable" regression rather than be silently
    absorbed as a no-key result.
    """
    assert not _is_converged_no_key(exc)


def test_the_match_is_case_insensitive_but_not_a_substring_free_for_all():
    assert _is_converged_no_key(ValueError("NEGATIVE KEY RATE"))
    assert not _is_converged_no_key(ValueError("key rate is negative"))


# --------------------------------------------------------------------------
# The message is upstream English. Pin it, so a reword fails loudly.
# --------------------------------------------------------------------------

def test_the_upstream_message_still_says_what_we_match_on():
    """If TNO rewords this, every distance past ~254 km silently regresses.

    Without this test the failure mode is invisible: `_is_converged_no_key`
    quietly returns False, the exception propagates, and /verify goes back to
    claiming the engine is unavailable -- with no test failing anywhere.
    """
    files = sorted(TNO_SRC.glob("bb84*.py")) + sorted(TNO_SRC.glob("bbm92.py"))
    if not files:
        pytest.skip("tno-qkd-key-rate submodule not checked out")

    raising = []
    for f in files:
        src = f.read_text(encoding="utf-8")
        for m in re.finditer(r'error_msg = "([^"]*negative key rate[^"]*)"', src):
            raising.append((f.name, m.group(1)))

    assert raising, (
        "no 'negative key rate' message found in the vendored TNO sources. "
        "Either the submodule moved or upstream reworded it -- in which case "
        "_NO_KEY_MARKER in tno_backend.py no longer matches and a converged "
        "no-key result is being reported as engine_unavailable again."
    )
    for name, msg in raising:
        assert _is_converged_no_key(ValueError(msg)), (
            f"{name} raises {msg!r}, which the predicate does not recognise")


def test_all_three_estimators_use_the_same_wording():
    """bb84, bb84_single_photon and bbm92 each raise it independently."""
    found = {f.name for f in TNO_SRC.glob("*.py")
             if "negative key rate" in f.read_text(encoding="utf-8")}
    if not found:
        pytest.skip("tno-qkd-key-rate submodule not checked out")
    assert found >= {"bb84.py"}, found


# --------------------------------------------------------------------------
# The call site.
# --------------------------------------------------------------------------

def test_the_fallback_does_not_second_guess_a_converged_no_key():
    """Falling back would answer with a model we do not run.

    `BB84FullyAsymptoticKeyRateEstimate` assumes infinitely many decoy states
    and so reports a HIGHER rate than the two-decoy estimate. Using it to
    override a converged decoy "no key" would put a positive rate on /verify
    for a protocol the shipped source does not implement.
    """
    src = (REPO / "services" / "bb84-kme" / "app" / "backends"
           / "tno_backend.py").read_text(encoding="utf-8")
    decoy_branch = src.split("trying fully-asymptotic")[0]
    assert "_is_converged_no_key(e)" in decoy_branch, (
        "the decoy branch no longer returns early on a converged no-key, so a "
        "more optimistic model can now overwrite it")


def test_a_converged_zero_is_labelled_as_one():
    """A caller must distinguish this zero from any other zero."""
    src = (REPO / "services" / "bb84-kme" / "app" / "backends"
           / "tno_backend.py").read_text(encoding="utf-8")
    assert '"no_key_reason"' in src, (
        "rate_per_pulse 0.0 with no marker is indistinguishable from a zero "
        "produced some other way")
