/**
 * The browser's key-rate curves reproduce the Python reference, digit for digit
 * where no optimiser is involved. tests/test_protocol_rates.py holds the reference
 * itself to the sources: exact linear optics for the single-photon terms, a direct
 * integration for the overall gain, and the curves of Lo, Curty and Qi, Fig. 2.
 */
import { describe, expect, it } from "vitest";

import golden from "./protocolRatesGolden.json";
import {
  PUBLISHED_RATE_PARAMS, backgroundPerSide, bb84Rate, bb84Terms, bbm92GainQber, bbm92Rate, besselI0,
  fibreTransmittance, maxDistanceKm, mdiE11, mdiGainRect, mdiRate, mdiY11, plobBound, ratePoint,
} from "./protocolRates";

const close = (a: number, b: number, rel = 1e-12) =>
  expect(Math.abs(a - b)).toBeLessThanOrEqual(rel * Math.max(Math.abs(b), 1e-300));

describe("the golden vectors", () => {
  it.each(golden.mdi)("MDI-QKD at eta $eta_a, $eta_b", (c) => {
    close(mdiY11(c.eta_a, c.eta_b, c.pd), c.y11);
    close(mdiE11(c.eta_a, c.eta_b, c.pd, c.e_d), c.e11);
    const g = mdiGainRect(c.eta_a, c.eta_b, c.mu_a, c.mu_b, c.pd, c.e_d);
    close(g.q, c.q_rect);
    close(g.e, c.e_rect);
    close(mdiRate(c.eta_a, c.eta_b, c.mu_a, c.mu_b, c.pd, c.e_d, c.f), c.rate, 1e-11);
  });

  it.each(golden.bbm92)("BBM92 at eta $eta_a, $eta_b", (c) => {
    const g = bbm92GainQber(c.eta_a, c.eta_b, c.lambda, c.y0, c.e_d);
    close(g.q, c.gain, 1e-11);
    close(g.e, c.qber, 1e-11);
    close(bbm92Rate(c.eta_a, c.eta_b, c.lambda, c.y0, c.e_d, c.f), c.rate, 1e-10);
  });

  it.each(golden.bb84)("decoy-state BB84 at eta $eta", (c) => {
    const t = bb84Terms(c.eta, c.mu, c.y0, c.e_d);
    close(t.q, c.gain);
    close(t.e, c.qber);
    close(t.q1, c.q1);
    close(t.e1, c.e1);
    close(bb84Rate(c.eta, c.mu, c.y0, c.e_d, c.f), c.rate, 1e-11);
  });
});

describe("the curves at the published parameters", () => {
  it.each(golden.curve)("match the reference at $length_km km", (row) => {
    for (const name of ["bb84", "bbm92", "mdi"] as const) {
      const got = ratePoint(name, row.length_km, PUBLISHED_RATE_PARAMS);
      close(got.rate, row[name].rate, 1e-9);
      expect(got.intensity === null).toBe(row[name].intensity === null);
    }
  });

  it("give the same longest fibre", () => {
    for (const name of ["bb84", "bbm92", "mdi"] as const) {
      expect(maxDistanceKm(name, PUBLISHED_RATE_PARAMS)).toBe(golden.max_distance_km[name]);
    }
    expect(maxDistanceKm("mdi", PUBLISHED_RATE_PARAMS, 0.25)).toBe(golden.max_distance_km_relay_at_a_quarter.mdi);
  });

  it("use the published parameters, which the reference names too", () => {
    expect(PUBLISHED_RATE_PARAMS).toEqual({
      alphaDbPerKm: golden.published_parameters.alpha, etaD: golden.published_parameters.eta_d,
      pd: golden.published_parameters.pd, eD: golden.published_parameters.e_d, f: golden.published_parameters.f,
    });
  });
});

describe("the pieces", () => {
  it("I0 is 1 at 0 and matches its value at 1 and 5", () => {
    expect(besselI0(0)).toBe(1);
    close(besselI0(1), 1.2660658777520084, 1e-14);
    close(besselI0(5), 27.239871823604442, 1e-14);
  });

  it("no key at a dark channel, and no rate is ever negative where a curve is drawn", () => {
    const dark = { ...PUBLISHED_RATE_PARAMS, alphaDbPerKm: 5 };
    for (const name of ["bb84", "bbm92", "mdi"] as const) {
      const far = ratePoint(name, 500, dark);
      expect(far.rate).toBe(0);
      expect(far.intensity).toBeNull();
    }
  });

  it("never lets a protocol pass the repeaterless bound over the same fibre", () => {
    for (const length of [10, 50, 100, 200, 300]) {
      const bound = plobBound(fibreTransmittance(PUBLISHED_RATE_PARAMS.alphaDbPerKm, length));
      for (const name of ["bb84", "bbm92", "mdi"] as const) {
        expect(ratePoint(name, length, PUBLISHED_RATE_PARAMS).rate).toBeLessThan(bound);
      }
    }
  });

  it("counts both detectors at one end as background", () => {
    close(backgroundPerSide(3e-6), 2 * 3e-6 - 9e-12, 1e-9);
  });

  it("gets worse as the relay leaves the middle, at the same total fibre", () => {
    const mid = ratePoint("mdi", 150, PUBLISHED_RATE_PARAMS, 0.5).rate;
    const off = ratePoint("mdi", 150, PUBLISHED_RATE_PARAMS, 0.15).rate;
    expect(mid).toBeGreaterThan(0);
    expect(off).toBeLessThanOrEqual(mid);
  });
});
