#!/usr/bin/env python3
"""Reference for the asymptotic key-rate curves on /qkd-protocols.

The browser port is services/webui-frontend/src/lib/sim/protocolRates.ts. Both
reproduce services/webui-frontend/src/lib/sim/protocolRatesGolden.json, which
this file writes; tests/test_protocol_rates.py and protocolRates.test.ts assert
it, and docs/keyrate.md section 9 derives every formula here.

Standard library only, so it can be read and run without the KME's environment.

    python3 tools/protocol_rates.py --write   # rewrite the golden file
    python3 tools/protocol_rates.py           # print it
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

GOLDEN = (
    Path(__file__).resolve().parent.parent
    / "services" / "webui-frontend" / "src" / "lib" / "sim" / "protocolRatesGolden.json"
)

# Lo, Curty and Qi (2012), caption of Fig. 2 and its text; the per-detector
# background is Ma and Razavi (2012), Table I.
PUBLISHED = {"alpha": 0.2, "eta_d": 0.145, "pd": 3.0e-6, "e_d": 0.015, "f": 1.16}

INTENSITY_LO = 1e-4
INTENSITY_HI = 3.0
GRID_POINTS = 61
GOLDEN_STEPS = 48
GOLDEN_RATIO = (math.sqrt(5.0) - 1.0) / 2.0


def h2(x: float) -> float:
    return -x * math.log2(x) - (1.0 - x) * math.log2(1.0 - x) if 0.0 < x < 1.0 else 0.0


def bessel_i0(x: float) -> float:
    """Modified Bessel function I0, by its power series."""
    term = 1.0
    total = 1.0
    k = 1
    while True:
        term *= (x * x / 4.0) / (k * k)
        total += term
        k += 1
        if term < 1e-17 * total:
            return total


def fibre(alpha: float, length_km: float) -> float:
    return 10.0 ** (-alpha * length_km / 10.0)


# ---- MDI-QKD: Ma and Razavi (2012), Appendixes A and B ----------------------
def mdi_y11(eta_a: float, eta_b: float, pd: float) -> float:
    return (1 - pd) ** 2 * (
        eta_a * eta_b / 2 + (2 * eta_a + 2 * eta_b - 3 * eta_a * eta_b) * pd
        + 4 * (1 - eta_a) * (1 - eta_b) * pd * pd
    )


def mdi_e11(eta_a: float, eta_b: float, pd: float, e_d: float) -> float:
    y11 = mdi_y11(eta_a, eta_b, pd)
    if y11 <= 0.0:
        return 0.5
    return (0.5 * y11 - (0.5 - e_d) * (1 - pd) ** 2 * eta_a * eta_b / 2) / y11


def mdi_gain_rect(eta_a, eta_b, mu_a, mu_b, pd, e_d):
    mu_prime = eta_a * mu_a + eta_b * mu_b
    x = math.sqrt(eta_a * mu_a * eta_b * mu_b) / 2
    q_c = (
        2 * (1 - pd) ** 2 * math.exp(-mu_prime / 2)
        * (1 - (1 - pd) * math.exp(-eta_a * mu_a / 2))
        * (1 - (1 - pd) * math.exp(-eta_b * mu_b / 2))
    )
    q_e = (
        2 * pd * (1 - pd) ** 2 * math.exp(-mu_prime / 2)
        * (bessel_i0(2 * x) - (1 - pd) * math.exp(-mu_prime / 2))
    )
    q = q_c + q_e
    e = (e_d * q_c + (1 - e_d) * q_e) / q if q > 0.0 else 0.5
    return q, e


def mdi_rate(eta_a, eta_b, mu_a, mu_b, pd, e_d, f) -> float:
    q11 = mu_a * mu_b * math.exp(-mu_a - mu_b) * mdi_y11(eta_a, eta_b, pd)
    q, e = mdi_gain_rect(eta_a, eta_b, mu_a, mu_b, pd, e_d)
    return q11 * (1 - h2(mdi_e11(eta_a, eta_b, pd, e_d))) - q * f * h2(e)


# ---- BBM92 from a thermal PDC source: Ma, Fung and Lo (2007), Eqs. (9)-(12) ---
def bbm92_gain_qber(eta_a, eta_b, lam, y0, e_d):
    a = 1 + eta_a * lam
    b = 1 + eta_b * lam
    c = 1 + eta_a * lam + eta_b * lam - eta_a * eta_b * lam
    q = 1 - (1 - y0) / a**2 - (1 - y0) / b**2 + (1 - y0) ** 2 / c**2
    if q <= 0.0:
        return 0.0, 0.5
    e = (0.5 * q - 2 * (0.5 - e_d) * eta_a * eta_b * lam * (1 + lam) / (a * b * c)) / q
    return q, e


def bbm92_rate(eta_a, eta_b, lam, y0, e_d, f) -> float:
    q, e = bbm92_gain_qber(eta_a, eta_b, lam, y0, e_d)
    return q * (1 - f * h2(e) - h2(e))


# ---- Decoy-state BB84, infinite decoys: docs/keyrate.md sections 2, 3 and 6 ----
def bb84_terms(eta, mu, y0, e_d):
    q = y0 + 1 - math.exp(-eta * mu)
    e = (y0 / 2 + e_d * (1 - math.exp(-eta * mu))) / q if q > 0.0 else 0.5
    y1 = y0 + eta - y0 * eta
    e1 = (y0 / 2 + e_d * eta) / y1 if y1 > 0.0 else 0.5
    q1 = y1 * mu * math.exp(-mu)
    return q, e, q1, e1


def bb84_rate(eta, mu, y0, e_d, f) -> float:
    q, e, q1, e1 = bb84_terms(eta, mu, y0, e_d)
    return q1 * (1 - h2(e1)) - f * q * h2(e)


# ---- The repeaterless bound: Pirandola et al. (2017), Eq. (19) -----------------
def plob(eta: float) -> float:
    return -math.log2(1 - eta) if 0.0 < eta < 1.0 else math.inf


def best_over(fn, lo=INTENSITY_LO, hi=INTENSITY_HI):
    """The best value of fn on [lo, hi]: a log grid, then a golden section around its best."""
    ratio = (hi / lo) ** (1 / (GRID_POINTS - 1))
    best_i = 0
    best_v = -math.inf
    for i in range(GRID_POINTS):
        v = fn(lo * ratio**i)
        if v > best_v:
            best_v = v
            best_i = i
    a = lo * ratio ** max(0, best_i - 1)
    b = lo * ratio ** min(GRID_POINTS - 1, best_i + 1)
    c = b - GOLDEN_RATIO * (b - a)
    d = a + GOLDEN_RATIO * (b - a)
    fc = fn(c)
    fd = fn(d)
    for _ in range(GOLDEN_STEPS):
        if fc > fd:
            b, d, fd = d, c, fc
            c = b - GOLDEN_RATIO * (b - a)
            fc = fn(c)
        else:
            a, c, fc = c, d, fd
            d = a + GOLDEN_RATIO * (b - a)
            fd = fn(d)
    at = c if fc > fd else d
    v = max(fc, fd)
    return (v, at) if v >= best_v else (best_v, lo * ratio**best_i)


def background_per_side(pd: float) -> float:
    """Two detectors at one end: the probability that at least one fires in the dark."""
    return 1 - (1 - pd) ** 2


def curve_point(protocol: str, length_km: float, p: dict, relay_share: float = 0.5):
    """(rate, intensity) at this length, the rate zero when no key survives."""
    if protocol == "bb84":
        eta = p["eta_d"] * fibre(p["alpha"], length_km)
        y0 = background_per_side(p["pd"])
        fn = lambda mu: bb84_rate(eta, mu, y0, p["e_d"], p["f"])  # noqa: E731
    else:
        eta_a = p["eta_d"] * fibre(p["alpha"], length_km * relay_share)
        eta_b = p["eta_d"] * fibre(p["alpha"], length_km * (1 - relay_share))
        if protocol == "bbm92":
            y0 = background_per_side(p["pd"])
            fn = lambda lam: bbm92_rate(eta_a, eta_b, lam, y0, p["e_d"], p["f"])  # noqa: E731
        else:
            balance = eta_a / eta_b
            fn = lambda mu: mdi_rate(  # noqa: E731
                eta_a, eta_b, mu, mu * balance, p["pd"], p["e_d"], p["f"])
    v, at = best_over(fn)
    return (v, at) if v > 0.0 else (0.0, None)


def max_distance(protocol: str, p: dict, relay_share: float = 0.5, top_km: float = 1000.0) -> float:
    """The longest fibre that still gives key, to 0.1 km."""
    if curve_point(protocol, 0.0, p, relay_share)[0] <= 0.0:
        return 0.0
    lo = 0.0
    hi = top_km
    if curve_point(protocol, hi, p, relay_share)[0] > 0.0:
        return hi
    while hi - lo > 0.1:
        mid = (lo + hi) / 2
        if curve_point(protocol, mid, p, relay_share)[0] > 0.0:
            lo = mid
        else:
            hi = mid
    return round(lo, 1)


def golden() -> dict:
    mdi_cases = []
    for eta_a, eta_b, mu_a, mu_b, pd, e_d, f in [
        (0.145, 0.145, 0.6, 0.6, 3.0e-6, 0.015, 1.16),
        (0.0145, 0.0145, 0.55, 0.55, 3.0e-6, 0.015, 1.16),
        (0.00145, 0.00145, 0.5, 0.5, 3.0e-6, 0.015, 1.16),
        (0.1, 0.1, 0.3, 0.3, 1.0e-6, 0.015, 1.16),
        (0.3, 0.03, 0.2, 2.0, 1.0e-6, 0.02, 1.1),
        (0.5, 0.5, 1.0, 1.0, 0.0, 0.0, 1.0),
    ]:
        q, e = mdi_gain_rect(eta_a, eta_b, mu_a, mu_b, pd, e_d)
        mdi_cases.append({
            "eta_a": eta_a, "eta_b": eta_b, "mu_a": mu_a, "mu_b": mu_b, "pd": pd, "e_d": e_d, "f": f,
            "y11": mdi_y11(eta_a, eta_b, pd), "e11": mdi_e11(eta_a, eta_b, pd, e_d),
            "q_rect": q, "e_rect": e, "rate": mdi_rate(eta_a, eta_b, mu_a, mu_b, pd, e_d, f),
        })
    bbm92_cases = []
    for eta_a, eta_b, lam, y0, e_d, f in [
        (0.145, 0.145, 0.062, 6.02e-6, 0.015, 1.16),
        (0.0145, 0.0145, 0.054, 6.02e-6, 0.015, 1.16),
        (0.3, 0.05, 0.1, 1.0e-6, 0.02, 1.1),
    ]:
        q, e = bbm92_gain_qber(eta_a, eta_b, lam, y0, e_d)
        bbm92_cases.append({
            "eta_a": eta_a, "eta_b": eta_b, "lambda": lam, "y0": y0, "e_d": e_d, "f": f,
            "gain": q, "qber": e, "rate": bbm92_rate(eta_a, eta_b, lam, y0, e_d, f),
        })
    bb84_cases = []
    for eta, mu, y0, e_d, f in [
        (0.045, 0.48, 1.7e-6, 0.033, 1.22),
        (0.145, 0.7, 6.02e-6, 0.015, 1.16),
        (0.00145, 0.66, 6.02e-6, 0.015, 1.16),
    ]:
        q, e, q1, e1 = bb84_terms(eta, mu, y0, e_d)
        bb84_cases.append({
            "eta": eta, "mu": mu, "y0": y0, "e_d": e_d, "f": f,
            "gain": q, "qber": e, "q1": q1, "e1": e1, "rate": bb84_rate(eta, mu, y0, e_d, f),
        })
    curve = []
    for length in (0, 25, 50, 100, 150, 200, 250, 300):
        row = {"length_km": length}
        for name in ("bb84", "bbm92", "mdi"):
            r, at = curve_point(name, float(length), PUBLISHED)
            row[name] = {"rate": r, "intensity": at}
        curve.append(row)
    return {
        "comment": "Written by tools/protocol_rates.py. Rates in bits per pulse (per pair of pulses for MDI), with the basis factor q = 1.",
        "published_parameters": PUBLISHED,
        "mdi": mdi_cases, "bbm92": bbm92_cases, "bb84": bb84_cases, "curve": curve,
        "max_distance_km": {n: max_distance(n, PUBLISHED) for n in ("bb84", "bbm92", "mdi")},
        "max_distance_km_relay_at_a_quarter": {"mdi": max_distance("mdi", PUBLISHED, 0.25)},
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true", help="rewrite the golden file")
    text = json.dumps(golden(), indent=1) + "\n"
    if ap.parse_args().write:
        GOLDEN.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
