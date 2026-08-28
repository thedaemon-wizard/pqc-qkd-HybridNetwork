/**
 * A measured rate must not render as zero.
 *
 * `/e2e` showed a "Throughput (Mbps)" card computed as
 * `((rate_bps ?? 0) / 1e6).toFixed(2)`. Every rate this simulator produces is
 * a few kbps, so the card read `0.00` always.
 *
 * Found in the browser on the deployed build, 2026-08-28. The run's two Data
 * Exchange phases, from the page's own history table:
 *
 *     rate_mbps 0.003576858446018516  ->  3577 bps  ->  card read "0.00"
 *     rate_mbps 0.008981990806995938  ->  8982 bps  ->  card read "0.01"
 *
 * The card showed `0.00` while the row beside it recorded a measured rate.
 *
 * A first draft of this file cited only the 0.008982 figure as the one that
 * rendered `0.00`. It does not -- it renders `0.01`. Both readings are useless
 * and both are the same defect, but attributing the wrong one would have put a
 * false arithmetic claim in a test whose whole subject is a number that does
 * not survive its own formatting.
 *
 * Both are also throttled hidden-tab readings. `dwellIsNotAMeasurement.test.ts`
 * already pins the foreground figure at 19 866 bps, which the old card showed
 * as `0.02`. The sweep below therefore spans the foreground range too, rather
 * than resting on two numbers from a backgrounded run.
 *
 * Nothing could catch it: the arithmetic was right, the field was populated,
 * and `toFixed(2)` did exactly what it says. Only the choice of unit was
 * wrong, and a unit is not something a test had been pointed at.
 *
 * The `?? 0` was the same fault twice. "No rate reported yet" and "the rate is
 * zero" rendered identically -- the substitution this page's comments reject
 * for QBER, and that `provenanceReachesTheScreen.test.ts` pins for the
 * synthetic-round flags.
 */
import { describe, expect, it } from "vitest";

import { formatRate } from "./QuantumSecureE2E";

const stripComments = (s: string) =>
  s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

describe("a rate is shown in a unit that can express it", () => {
  it.each([
    // Verbatim from the deployed run, with what the old card showed for each.
    [0.003576858446018516, "3.58", "0.00"],
    [0.008981990806995938, "8.98", "0.01"],
  ])("%f Mbps is legible (the card used to read %s)", (mbps, want, oldCard) => {
    const bps = mbps * 1e6;
    const got = formatRate(bps);
    expect(got.unit).toBe("kbps");
    expect(got.value).toBe(want);
    // Pin what the old expression did, so the motivating numbers stay honest:
    // one rounded to zero, the other to a single misleading significant figure.
    expect((bps / 1e6).toFixed(2)).toBe(oldCard);
  });

  it("no plausible simulator rate rounds away to zero", () => {
    // The observed range is single-digit kbps; span well past it both ways.
    for (const bps of [1, 12, 480, 3576, 8982, 19_866, 45_000, 999_999, 4.2e6]) {
      const { value } = formatRate(bps);
      expect(Number(value), `${bps} bps rendered as ${value}`).toBeGreaterThan(0);
    }
  });

  it("picks the unit from the magnitude", () => {
    expect(formatRate(940)).toEqual({ value: "940", unit: "bps" });
    expect(formatRate(1_000)).toEqual({ value: "1.00", unit: "kbps" });
    expect(formatRate(2_500_000)).toEqual({ value: "2.50", unit: "Mbps" });
    expect(formatRate(4.2e9)).toEqual({ value: "4.20", unit: "Gbps" });
  });

  it("promotes at the ROUNDING boundary, not the unit boundary", () => {
    // `toFixed` rounds after the branch is chosen, so selecting the unit at
    // 1e6 rendered 999_999 bps as "1000.00 kbps" -- a four-digit kilobit
    // figure, the same class of nonsense this function removes. The earlier
    // sweep contained 999_999 and walked straight over it, because it only
    // asserted the value was greater than zero.
    for (const bps of [999_995, 999_999, 999_999.5]) {
      expect(formatRate(bps), `${bps} bps`).toEqual({ value: "1.00", unit: "Mbps" });
    }
    expect(formatRate(999_994)).toEqual({ value: "999.99", unit: "kbps" });
    for (const bps of [999.5, 999.999]) {
      expect(formatRate(bps), `${bps} bps`).toEqual({ value: "1.00", unit: "kbps" });
    }
    expect(formatRate(999.4)).toEqual({ value: "999", unit: "bps" });
  });

  it("no output is a four-digit figure in a unit that should have promoted", () => {
    // The general form of the bug above, swept rather than spot-checked.
    for (let e = 0; e < 10; e++) {
      for (const m of [0.9995, 0.99999, 1, 1.5, 9.99, 9.9999]) {
        const bps = m * 10 ** e;
        const { value, unit } = formatRate(bps);
        if (unit === "bps") continue;               // bps has no lower unit
        expect(Math.abs(Number(value)), `${bps} bps -> ${value} ${unit}`)
          .toBeLessThan(1000);
      }
    }
  });

  it("a real zero is still zero, and says bps", () => {
    // Zero is a legitimate reading before any packet is sent. It must not be
    // conflated with absence in EITHER direction.
    expect(formatRate(0)).toEqual({ value: "0", unit: "bps" });
  });
});

describe("an absent rate is not a zero rate", () => {
  // Only `undefined` is reachable today: `rate_bps` is a non-optional number
  // initialised to 0, and `elapsed` is floored at 1e-3 so the division cannot
  // produce NaN or Infinity. The other three are defensive, and saying so is
  // better than implying the guard covers four live paths.
  it.each([undefined, null, NaN, Infinity])("%s renders as a dash", (v) => {
    const got = formatRate(v as number | null | undefined);
    expect(got.value).toBe("—");
    expect(got.unit).toBe("not reported");
  });

  it("the card no longer coerces a missing rate with ?? 0", async () => {
    const raw = await import("node:fs").then((fs) =>
      fs.readFileSync(new URL("./QuantumSecureE2E.tsx", import.meta.url), "utf8"));
    // Comments stripped first. The docstring on `formatRate` quotes the old
    // expression in order to retract it, and a bare scan flags that quotation
    // -- a guard failing on its own record of the fix. Sixth instance of this
    // shape in this suite; strip, do not special-case the wording.
    const code = stripComments(raw);
    expect(code, "the ?? 0 coercion is back on the throughput card")
      .not.toMatch(/rate_bps\s*\?\?\s*0/);
    expect(code).toMatch(/formatRate\(state\?\.rate_bps\)/);
  });

  it("that comment-stripping does not make the check vacuous", async () => {
    // If the stripper ate the code as well as the prose, the assertion above
    // would pass on an empty string.
    const raw = await import("node:fs").then((fs) =>
      fs.readFileSync(new URL("./QuantumSecureE2E.tsx", import.meta.url), "utf8"));
    const code = stripComments(raw);
    expect(code.length).toBeGreaterThan(raw.length * 0.5);
    expect(code).toContain("export default function");
    // Do NOT assert the docstring still quotes the old expression. A draft
    // did, and that turned a prose edit into a test failure: the branch
    // avoided a guard that flags its own text by adding one that MANDATES its
    // own text. Instead, prove the stripper removes a comment on a synthetic
    // input, which tests the mechanism without constraining the wording.
    // The `//` arm strips FULL-LINE comments only, deliberately: a trailing
    // `//` would also match inside a string or a URL. The probe has to respect
    // that, and a first draft did not -- it put the line comment after code
    // and then asserted it had been removed.
    const probe = "/* rate_bps ?? 0 */ const x = 1;\n  // rate_bps ?? 0\nconst y = 2;";
    expect(stripComments(probe)).not.toMatch(/rate_bps/);
    expect(stripComments(probe)).toContain("const x = 1;");
    expect(stripComments(probe)).toContain("const y = 2;");
  });
});
