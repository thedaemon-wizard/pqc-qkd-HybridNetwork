"""The `sequence` backend has to get its noise from SeQUeNCe, and agree with Lo-Ma.

It did neither. The round function read

    noise_rate = Noise().depolarizing_rate if hasattr(Noise, "depolarizing_rate") \\
                 else cfg.misalignment_error_ed

and `Noise` has never had a `depolarizing_rate` attribute -- it is a stateless
helper whose methods TAKE an error rate as a parameter and do not publish one.
So the `hasattr` was always False, the fallback always fired, and the next line

    e_d_eff = cfg.misalignment_error_ed + noise_rate

added `e_d` to itself. The backend reported a QBER computed from 2 * e_d and
described the result as SeQUeNCe's photonic noise model.

Two further details made it hard to notice:

  * the numpy generator was seeded from `cfg.rng_seed`, so every round returned
    byte-identical results -- a Monte-Carlo simulation with no variance;
  * `test_backend_cross_qber.py` parametrizes over "qutip" and "simqn" only, so
    nothing compared this backend against the analytical value.

Measured before the fix: QBER 0.046875 on every round, 3.1x the analytical
0.015001, identical on the v0.8.5-era pin and on v1.0.0 -- because the missing
attribute was missing in both.

Errors are now sampled per sifted bit through `Noise.apply_measurement_noise`,
which is SeQUeNCe's actual API. Measured after: mean 0.014583 over 60 rounds
against an analytical 0.015001, five distinct values.
"""
from __future__ import annotations

import asyncio
import os
import statistics
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "bb84-kme"))
os.environ.setdefault("QKD_PARAMS_FILE", str(ROOT / "config" / "qkd_params.yaml"))

ROUNDS = 60


def _backend():
    from app import config_loader
    config_loader.reload()
    from app.backends import make_backend
    from app.backends.base import cfg_from_yaml

    cfg = cfg_from_yaml()
    try:
        return make_backend("sequence", cfg), cfg
    except RuntimeError as e:  # pragma: no cover - depends on the image
        pytest.skip(f"sequence backend unavailable: {e}")


def _analytic(cfg) -> float:
    from app.backends._skr import qber_Emu, total_transmittance

    eta = total_transmittance(
        cfg.detector_efficiency, cfg.fiber_attenuation_db_per_km, cfg.link_length_km
    )
    Y0 = cfg.dark_count_rate_hz / cfg.pulse_rate_hz
    return qber_Emu(Y0, eta, cfg.misalignment_error_ed, cfg.intensity_signal_mu)


@pytest.fixture(scope="module")
def rounds():
    pytest.importorskip(
        "sequence",
        reason="SeQUeNCe is installed in the bb84-kme image, not on the host",
    )
    backend, cfg = _backend()
    return [asyncio.run(backend.run_round()).qber for _ in range(ROUNDS)], cfg


def test_the_noise_is_sampled_not_fixed(rounds):
    """A seeded constant is not a simulation.

    Before the fix every round returned exactly 0.046875. Requiring more than
    one distinct value is what separates sampling from a hardcoded outcome.
    """
    qbers, _ = rounds
    assert len(set(qbers)) > 1, (
        f"all {len(qbers)} rounds returned the same QBER ({qbers[0]}). The "
        "backend is not sampling -- check that the generator is not seeded to a "
        "constant and that errors come from Noise.apply_measurement_noise."
    )


def test_the_mean_agrees_with_the_analytical_qber(rounds):
    """Convergence to Lo-Ma, which the doubled e_d broke by a factor of ~3.

    Tolerance is 25 %: with ~64 sifted bits per round the QBER is quantised at
    1/64 = 0.0156, which is itself the same order as the value being measured,
    so a tighter bound would fail on sampling noise rather than on a defect.
    """
    qbers, cfg = rounds
    analytic = _analytic(cfg)
    mean = statistics.mean(qbers)
    assert abs(mean - analytic) <= 0.25 * analytic, (
        f"mean QBER {mean:.6f} over {len(qbers)} rounds against an analytical "
        f"{analytic:.6f} (ratio {mean / analytic:.2f}). A ratio near 2 means "
        "e_d is being added to itself again; near 3 means that plus the old "
        "fixed seed."
    )


def test_the_removed_fallback_is_not_reinstated():
    """The specific line that manufactured the number.

    Guarding the source text as well as the behaviour, because the behavioural
    test needs SeQUeNCe installed and skips on the host, where most people run
    the suite.
    """
    src = (ROOT / "services" / "bb84-kme" / "app" / "backends"
           / "sequence_backend.py").read_text(encoding="utf-8")

    # Strip comments before matching. The file explains the old defect at
    # length and necessarily names `depolarizing_rate` while doing so; a
    # substring search over the raw text fails on that explanation, which is
    # how the first version of this assertion behaved.
    code = "\n".join(
        line.split("#", 1)[0] for line in src.splitlines()
    )

    for pattern, why in [
        ('depolarizing_rate', "that attribute does not exist on SeQUeNCe's "
                              "Noise class, so any guard around it always "
                              "takes the fallback branch"),
        ('misalignment_error_ed + noise_rate', "e_d is being added to a second "
                                               "copy of itself again"),
    ]:
        assert pattern not in code, f"sequence_backend.py: {pattern!r} is back -- {why}"

    # And the replacement must still be present, or this file is only asserting
    # the absence of something while the backend computes nothing at all.
    assert "apply_measurement_noise" in code, (
        "the backend no longer calls Noise.apply_measurement_noise, so its "
        "errors are not coming from SeQUeNCe."
    )
