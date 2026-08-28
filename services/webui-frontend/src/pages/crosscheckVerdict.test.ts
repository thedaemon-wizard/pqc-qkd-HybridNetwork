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
