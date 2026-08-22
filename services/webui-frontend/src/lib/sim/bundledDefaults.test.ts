/**
 * One bundled parameter set, and every engine derives from it.
 *
 * There were three. `BB84.tsx` held the config-matching values while
 * `bb84Sim.ts` and `bb84.worker.ts` each held a hardcoded
 * `{ etaTotal: 0.02, Y0: 1e-5 }` describing a different channel entirely --
 * 6.3x more lossy with 100x the dark-count yield.
 *
 * That was reachable, not theoretical. The worker starts immediately so the
 * page has data to draw, and `/api/sim/params` arrives later, so the first
 * rounds a viewer saw were computed on the wrong channel and charted next to
 * a threshold line taken from the right one.
 *
 * The deeper mistake was treating eta_total and Y0 as inputs. They are
 * DERIVED from detector efficiency, attenuation, length, dark-count rate and
 * pulse rate; writing them as literals is what allowed them to drift away from
 * the parameters they follow.
 */
import { describe, expect, it } from "vitest";

import { BUNDLED_PARAMS, bundledChannel, channelFromParams } from "./keyrate";

describe("the bundled channel is derived, not stated", () => {
  it("matches channelFromParams applied to the bundled parameters", () => {
    const expected = channelFromParams(BUNDLED_PARAMS);
    const actual = bundledChannel();
    expect(actual.etaTotal).toBe(expected.etaTotal);
    expect(actual.Y0).toBe(expected.Y0);
  });

  it("follows the parameters when they change", () => {
    // The property a literal cannot have. Doubling the link length must move
    // eta_total; if this ever passes with a constant, the derivation is gone.
    const longer = channelFromParams({ ...BUNDLED_PARAMS, linkLengthKm: 20 });
    expect(longer.etaTotal).toBeLessThan(bundledChannel().etaTotal);
  });

  it("is not the old hardcoded channel", () => {
    // Pinned explicitly so a well-meaning "restore the previous defaults"
    // fails loudly. 0.02 / 1e-5 were the values two engines carried.
    const { etaTotal, Y0 } = bundledChannel();
    expect(etaTotal).not.toBeCloseTo(0.02, 6);
    expect(Y0).not.toBeCloseTo(1e-5, 9);
    // And what they should be, from 0.2 efficiency, 0.2 dB/km, 10 km,
    // 100 Hz dark counts, 1 GHz pulses.
    expect(etaTotal).toBeCloseTo(0.12619, 4);
    expect(Y0).toBeCloseTo(1e-7, 12);
  });

  it("exposes the abort threshold rather than leaving it to the chart", () => {
    expect(BUNDLED_PARAMS.qberThresholdAbort).toBe(0.11);
  });
});
