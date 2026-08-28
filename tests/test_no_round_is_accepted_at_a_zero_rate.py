"""A round must not be handed out as a key at a modelled rate of zero.

`config/qkd_params.yaml` sets `qber_threshold_abort: 0.11` and, until this
change, labelled it "Lo-Ma asymptotic bound". It is not. 11.003 % is the
Shor-Preskill root of `1 - 2*h2(e) = 0`, which holds for **ideal single photons
with perfect error correction**. What ships is a decoy-state weak-coherent
source with `f_EC = 1.16`, whose GLLP rate vanishes far earlier -- measured on
the shipped parameters at **QBER 6.602 %, L = 253.51 km**.

Two of the three backends tested only the QBER, so between the two numbers
there is a band of distances where a 256-bit key was minted at a modelled rate
of exactly zero:

       L(km)    QBER    rate/pulse   old predicate   new predicate
         253  0.06495  3.29e-09      accept          accept
         254  0.06705  0.000000      accept          REJECT
         270  0.11237  0.000000      abort           REJECT

Nothing in the build could have failed on the middle row. `accepted` was true,
`skr_bps` was 0.0, and both were reported side by side as a healthy round --
`/verify` even displayed the zero. `link_length_km` is an unbounded field on
`/physics`, so it is reachable from the public demo in one edit.

`tno_backend.py` already had the correct two-condition predicate. These tests
pin the band and pin the fact that all three backends now share one predicate
rather than each re-deciding.
"""
from __future__ import annotations

import math
import pathlib
import sys

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "bb84-kme"))

from app.backends._skr import (  # noqa: E402
    accepts_round,
    asymptotic_skr_per_pulse,
    qber_Emu,
    skr_bps_from_config,
    total_transmittance,
)

BACKENDS = REPO / "services" / "bb84-kme" / "app" / "backends"

# Read from the shipped config, not retyped. The first draft of this file
# hardcoded eta_det = 0.1 and nu1 = 0.05 against an actual 0.2 and 0.1, which
# moved the computed crossing from 253.5 km to somewhere past the abort
# threshold -- i.e. it would have "proved" the band does not exist.
_CFG = yaml.safe_load((REPO / "config" / "qkd_params.yaml").read_text(encoding="utf-8"))
_PHY, _SRC, _PROTO = _CFG["physical"], _CFG["source"], _CFG["protocol"]

MU = float(_SRC["intensity_signal_mu"])
ND1 = float(_SRC["intensity_decoy_1_nu1"])
ND2 = float(_SRC["intensity_decoy_2_nu2"])
E_D = float(_PHY["misalignment_error_ed"])
F_EC = float(_PROTO["ec_efficiency_f"])
ETA_DET = float(_PHY["detector_efficiency"])
ATT_DB_KM = float(_PHY["fiber_attenuation_db_per_km"])
DARK_HZ = float(_PHY["dark_count_rate_hz"])
PULSE_HZ = float(_SRC["pulse_rate_hz"])
ABORT = float(_PROTO["qber_threshold_abort"])


class _Cfg:
    qber_threshold_abort = ABORT


class _FullCfg:
    """The fields skr_bps_from_config reads. Values from the shipped YAML."""
    detector_efficiency = ETA_DET
    fiber_attenuation_db_per_km = ATT_DB_KM
    dark_count_rate_hz = DARK_HZ
    pulse_rate_hz = PULSE_HZ
    misalignment_error_ed = E_D
    intensity_signal_mu = MU
    intensity_decoy_1_nu1 = ND1
    intensity_decoy_2_nu2 = ND2
    ec_efficiency_f = F_EC
    block_size_N = int(_PROTO["block_size_N"])
    security_epsilon = float(_PROTO["security_epsilon"])
    qber_threshold_abort = ABORT


def _shipped_bps(km: float) -> float:
    """Exactly what the backends feed accepts_round.

    THIS is the path production takes. An earlier version of this file called
    `asymptotic_skr_per_pulse` directly, which is a DIFFERENT curve --
    skr_bps_from_config uses skr_finite -- so the file passed while asserting a
    band 160 km from the one the shipped predicate produces. Testing a function
    production does not call is the defect class this whole suite exists to
    remove, and it was reintroduced here.
    """
    cfg = _FullCfg()
    cfg.link_length_km = km
    return skr_bps_from_config(cfg)


def _at(km: float) -> tuple[float, float]:
    """(QBER, ASYMPTOTIC rate per pulse) -- the curve the UI displays.

    Kept for the two tests that are about the displayed curve. Anything about
    ACCEPTANCE must use _shipped_bps.
    """
    eta = total_transmittance(ETA_DET, ATT_DB_KM, km)
    Y0 = DARK_HZ / PULSE_HZ
    return (
        qber_Emu(Y0, eta, E_D, MU),
        asymptotic_skr_per_pulse(Y0=Y0, eta_total=eta, e_d=E_D, mu=MU,
                                 nu1=ND1, nu2=ND2, f_EC=F_EC),
    )


# --------------------------------------------------------------------------
# The band exists, and it is where it was measured.
# --------------------------------------------------------------------------

def test_the_rate_crosses_zero_well_before_the_abort_threshold():
    """The premise. If this stops holding, the band closed and so does the bug."""
    lo, hi = 0.0, 1000.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if _at(mid)[1] > 0.0:
            lo = mid
        else:
            hi = mid
    qber_at_zero = _at(hi)[0]
    assert hi == pytest.approx(253.51, abs=0.5), f"crossing moved to {hi:.2f} km"
    assert qber_at_zero == pytest.approx(0.06602, abs=1e-4)
    assert qber_at_zero < ABORT, (
        "the rate now vanishes at or above the abort threshold, which would "
        "mean the QBER test alone is sufficient after all")


def test_shor_preskill_is_11_percent_and_is_a_different_number():
    """0.11 is defensible as a ceiling; it is just not the rate's zero."""
    lo, hi = 0.0, 0.5
    for _ in range(200):
        mid = (lo + hi) / 2
        h2 = -mid * math.log2(mid) - (1 - mid) * math.log2(1 - mid)
        if 1 - 2 * h2 > 0:
            lo = mid
        else:
            hi = mid
    assert hi == pytest.approx(0.11003, abs=1e-4)
    assert not math.isclose(hi, _at(253.6)[0], rel_tol=0.1), (
        "the two bounds are being conflated again")


@pytest.mark.parametrize("km,expect_key", [
    (10.0, True), (90.0, True), (93.0, True),
    (93.3, False),       # the dead band OPENS here, not at 254 km
    (100.0, False),
    (150.0, False),
    (254.0, False),
    (270.0, False),      # past the abort threshold too
])
def test_the_predicate_rejects_the_whole_dead_band(km, expect_key):
    """Driven through skr_bps_from_config -- the shipped path."""
    qber, _ = _at(km)
    bps = _shipped_bps(km)
    assert accepts_round(qber, bps, _Cfg) is expect_key, (
        f"L={km} km: QBER {qber:.5f}, shipped skr_bps {bps:.4e}")


def test_qber_alone_would_have_accepted_the_band():
    """Show the old predicate failing, so this file is not vacuous."""
    for km in (100.0, 150.0, 200.0, 254.0):
        qber = _at(km)[0]
        bps = _shipped_bps(km)
        assert qber < ABORT, f"premise: the old QBER-only test passes at {km} km"
        assert bps == 0.0, f"premise: but the shipped rate is zero at {km} km"
        assert accepts_round(qber, bps, _Cfg) is False


def test_the_shipped_curve_is_not_the_displayed_curve():
    """160 km apart, and conflating them is how this file first went wrong.

    `/physics` and `/verify` show the asymptotic GLLP rate; `accepts_round` is
    fed the finite-key one. Between 93.3 and 253.5 km the UI shows a positive
    rate for a link the backend will not mint a key on.
    """
    qber, asym = _at(150.0)
    assert asym > 0.0, "the displayed curve is positive at 150 km"
    assert _shipped_bps(150.0) == 0.0, "the accepted curve is zero at 150 km"
    assert qber < ABORT, "and the QBER test would have passed"


def test_the_two_crossings_are_where_the_docs_say():
    """Pin both, so neither number can drift without the other being checked."""
    def crossing(f):
        lo, hi = 1.0, 1000.0
        for _ in range(200):
            mid = (lo + hi) / 2
            if f(mid) > 0.0:
                lo = mid
            else:
                hi = mid
        return hi
    shipped = crossing(_shipped_bps)
    displayed = crossing(lambda km: _at(km)[1])
    assert shipped == pytest.approx(93.3, abs=0.5), f"shipped {shipped:.2f} km"
    assert displayed == pytest.approx(253.51, abs=0.5), f"displayed {displayed:.2f} km"
    assert displayed - shipped == pytest.approx(160.2, abs=1.0)


def test_the_abort_ceiling_still_applies_on_its_own():
    """A positive rate does not override the QBER ceiling."""
    assert accepts_round(0.11, 1.0e6, _Cfg) is False
    assert accepts_round(0.5, 1.0e9, _Cfg) is False
    assert accepts_round(0.1099, 1.0e6, _Cfg) is True


# --------------------------------------------------------------------------
# One predicate, not three.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("backend", ["simqn_backend", "sequence_backend", "tno_backend"])
def test_every_backend_routes_through_the_shared_predicate(backend):
    src = (BACKENDS / f"{backend}.py").read_text(encoding="utf-8")
    assert "accepts_round(" in src, (
        f"{backend} decides acceptance itself; it can drift back to a "
        f"QBER-only test without anything noticing")


@pytest.mark.parametrize("backend", ["simqn_backend", "sequence_backend"])
def test_no_backend_still_tests_the_qber_threshold_alone(backend):
    """The exact expressions that produced the band."""
    src = (BACKENDS / f"{backend}.py").read_text(encoding="utf-8")
    for banned in (
        "bool(key) and qber < self.cfg.qber_threshold_abort",
        "qber_obs >= cfg.qber_threshold_abort",
    ):
        assert banned not in src, f"{backend} restored the QBER-only test: {banned}"


def test_the_config_comment_no_longer_misattributes_the_threshold():
    txt = (REPO / "config" / "qkd_params.yaml").read_text(encoding="utf-8")
    line = next(ln for ln in txt.splitlines()
                if ln.strip().startswith("qber_threshold_abort:"))
    assert "Lo-Ma" not in line, (
        "0.11 is Shor-Preskill for ideal single photons, not the Lo-Ma "
        "decoy-state bound the shipped source actually obeys")
    assert "Shor-Preskill" in txt
