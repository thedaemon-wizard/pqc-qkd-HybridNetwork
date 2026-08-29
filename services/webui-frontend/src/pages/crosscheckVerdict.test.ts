/**
 * /verify must not print "review" for five different things.
 *
 * The page rendered `same_order_of_magnitude ? "YES ✓ (independent agreement)"
 * : "review"`, and one line below it a paragraph asserted unconditionally that
 * the two implementations "agree to order of magnitude". So in the failing
 * render the table said review and the prose beneath it said agree.
 *
 * The case that matters: at any link beyond 253.51 km both implementations
 * return exactly 0 -- they agree completely -- and that rendered as "review",
 * the same word as "the TNO optimiser is not installed".
 */
import { describe, expect, it } from "vitest";

import { VERDICT_DISPLAY, describeVerdict } from "./crosscheckVerdict";
import type { CrosscheckVerdict } from "./crosscheckVerdict";

const ALL = Object.keys(VERDICT_DISPLAY) as CrosscheckVerdict[];

describe("every verdict is distinguishable on screen", () => {
  it("covers exactly the five states the API can return", () => {
    expect(ALL.sort()).toEqual([
      "agree", "disagree", "engine_unavailable",
      "neither_predicts_a_key", "one_side_zero",
    ]);
  });

  it("no two verdicts share a label", () => {
    const labels = ALL.map((v) => VERDICT_DISPLAY[v].label);
    expect(new Set(labels).size, "two states would read identically").toBe(ALL.length);
  });

  it("no two verdicts share a detail sentence", () => {
    const details = ALL.map((v) => VERDICT_DISPLAY[v].detail);
    expect(new Set(details).size).toBe(ALL.length);
  });

  it("nothing renders the old catch-all word", () => {
    for (const v of ALL) {
      expect(VERDICT_DISPLAY[v].label.toLowerCase())
        .not.toBe("review");
    }
  });
});

describe("colour does not overstate the result", () => {
  it("only a genuine ratio agreement is green", () => {
    const green = ALL.filter((v) => VERDICT_DISPLAY[v].ok === true);
    expect(green).toEqual(["agree"]);
  });

  it("both-zero is neutral, not green and not amber", () => {
    // The implementations DO agree, so amber would misreport it as a problem
    // with the cross-check. But green beside "no extractable key" would read
    // as a passing link. Neutral is the only honest colour.
    expect(VERDICT_DISPLAY.neither_predicts_a_key.ok).toBeUndefined();
  });

  it("an absent measurement is not painted as a negative result", () => {
    expect(VERDICT_DISPLAY.engine_unavailable.ok).toBeUndefined();
  });

  it("the two real problems are amber", () => {
    expect(VERDICT_DISPLAY.disagree.ok).toBe(false);
    expect(VERDICT_DISPLAY.one_side_zero.ok).toBe(false);
  });
});

describe("the detail sentence says why, not just what", () => {
  it("both-zero explains that no ratio exists rather than leaving a blank", () => {
    const d = VERDICT_DISPLAY.neither_predicts_a_key.detail;
    expect(d).toMatch(/agreement/i);
    expect(d).toMatch(/0\/0|no ratio/i);
  });

  it("engine_unavailable says absent measurement, not negative result", () => {
    expect(VERDICT_DISPLAY.engine_unavailable.detail).toMatch(/not a negative result/i);
  });
});

describe("an unknown verdict degrades safely", () => {
  it("a stale bundle against a newer API does not render green", () => {
    for (const v of ["some_new_state", "", 0, false, true, {}, []]) {
      expect(describeVerdict(v).ok, `${JSON.stringify(v)} was treated as agreement`)
        .toBeUndefined();
    }
  });

  it("null and undefined read as not reported, not as a failure", () => {
    for (const v of [null, undefined]) {
      expect(describeVerdict(v).label).toBe("Not reported");
      expect(describeVerdict(v).ok).toBeUndefined();
    }
  });

  it("a known verdict still resolves to its own entry", () => {
    for (const v of ALL) {
      expect(describeVerdict(v)).toBe(VERDICT_DISPLAY[v]);
    }
  });

  it("does not resolve inherited Object properties as verdicts", () => {
    // `"toString" in VERDICT_DISPLAY` is true via the prototype chain, so a
    // naive `in` check would return Object.prototype.toString as a display
    // object and the page would render "[object Object]" in green.
    for (const v of ["toString", "constructor", "hasOwnProperty", "__proto__"]) {
      const d = describeVerdict(v);
      expect(d.label, `${v} resolved through the prototype chain`)
        .toMatch(/^Unrecognised verdict/);
      expect(d.ok).toBeUndefined();
    }
  });
});

/**
 * The pass and fail labels must state the same threshold.
 *
 * `disagree` read "NO (rates differ by more than 10x)" -- threshold named.
 * `agree` read "YES (independent agreement)" -- threshold hidden, and the word
 * "agreement" doing work the check does not support. Measured on the deployed
 * build at the shipped config, the row directly above it showed
 * "Relative Delta 270.7 %": ours 1.233e-2 vs TNO 4.573e-2, a ratio of 3.71.
 * Both statements were true and the pair still misled, because the reader
 * takes "agreement" to mean the numbers matched.
 *
 * The asymmetry ran in the flattering direction, which is the only direction
 * worth a test.
 */
describe("the pass and fail labels are symmetric about the threshold", () => {
  it("the passing label names the band it passed", () => {
    expect(VERDICT_DISPLAY.agree.label).toMatch(/10x/);
  });

  it("the failing label still names it too", () => {
    expect(VERDICT_DISPLAY.disagree.label).toMatch(/10x/);
  });

  it("the passing label does not claim the numbers matched", () => {
    // "independent agreement" is the specific phrase that oversold a 3.7x gap.
    expect(VERDICT_DISPLAY.agree.label.toLowerCase())
      .not.toMatch(/independent agreement/);
  });

  it("the detail says this is an order-of-magnitude check, not a match", () => {
    expect(VERDICT_DISPLAY.agree.detail).toMatch(/order.of.magnitude/i);
    expect(VERDICT_DISPLAY.agree.detail).toMatch(/factor of 10/);
  });

  it("neither_predicts_a_key is still the one that is not painted green", () => {
    // Unchanged by this edit, and the reason the file exists. Two engines
    // agreeing that no key is extractable is agreement, but green would read
    // as "all good" on a link that carries nothing.
    expect(VERDICT_DISPLAY.neither_predicts_a_key.ok).toBeUndefined();
    expect(VERDICT_DISPLAY.agree.ok).toBe(true);
    expect(VERDICT_DISPLAY.disagree.ok).toBe(false);
  });
});
