/**
 * Rate formatting.
 *
 * Two formatters, because two different things are displayed as rates:
 *
 *   - `formatRate` is for values this site COMPUTES (simulated throughput). It
 *     picks a legible unit and rounds, which is right for a number the page
 *     made up and wrong for one it is quoting.
 *   - `formatReported` is for values a SOURCE printed. It keeps the source's
 *     own digits and unit. Passed through `formatRate`, "12.7 bit/s" would show
 *     as "13 bps" and "2 kbps" as "2.00 kbps" -- a precision the paper never
 *     claimed, which is the same fault in the other direction.
 */

/**
 * Pick a unit the measured rate is actually legible in.
 *
 * This card read `((rate_bps ?? 0) / 1e6).toFixed(2)`, and the rates this
 * simulator produces are a few kbps, so it had two decimal places to express a
 * number three orders of magnitude below its unit. Measured on the deployed
 * build 2026-08-28, the two Data Exchange phases in one run:
 *
 *     rate_mbps 0.003576858446018516  ->  3577 bps  ->  card read "0.00"
 *     rate_mbps 0.008981990806995938  ->  8982 bps  ->  card read "0.01"
 *
 * The card was showing `0.00` while the phase history beside it recorded a
 * measured rate: two panels on one screen, one saying throughput was measured
 * and the other saying there was none, with the wrong one in the larger font.
 *
 * The second line is the more instructive of the two. `0.01` is not a rescue --
 * it is a single significant figure that looks like a real reading, so it fails
 * quietly where `0.00` at least looks broken. Both are the same defect.
 *
 * Both of those are also THROTTLED readings, taken in a hidden tab. The caveat
 * is one file over, in `e2eSim.ts`: a foreground cycle is 4 x 500 ms (it was
 * documented as 4 x 450, which the 100 ms loop never achieved) and runs at
 * about 17.9 kbps, which the old card rendered `0.02`. So the fault was never
 * "always zero" -- it was one or two significant figures at every rate this
 * page produces, and the foreground case is the one that looks most like a
 * real measurement. (The /e2e card now calls it an animation-paced byte rate,
 * which is what it is.)
 *
 * The `?? 0` was the second half of the same fault: "the run has not reported a
 * rate yet" and "the rate is zero" rendered identically. That substitution is
 * the one this page's own comments reject for QBER, and
 * `provenanceReachesTheScreen.test.ts` pins it for the synthetic-round flags.
 * An absent rate is a dash.
 */
export function formatRate(bps: number | null | undefined):
    { value: string; unit: string } {
  if (typeof bps !== "number" || !Number.isFinite(bps)) {
    return { value: "—", unit: "not reported" };
  }
  // Thresholds are the ROUNDING boundaries, not the unit boundaries, because
  // `toFixed` rounds after the branch has already been chosen. Picking the
  // unit at 1e6 rendered 999_999 bps as "1000.00 kbps" -- a four-digit
  // kilobit reading, which is the same class of nonsense this function exists
  // to remove. 999_995 is the least value that rounds to 1.00 Mbps at two
  // decimals; 999.5 is the least that rounds to 1.00 kbps.
  // Gbps exists so Mbps is not the top unit. Without it a 1e9 rate rendered
  // "1000.00 Mbps", which is the same four-digit-in-the-wrong-unit reading the
  // thresholds above exist to prevent -- the guard would have had to exempt
  // its own top tier, which is how an exception becomes the bug.
  if (bps >= 999_999_500) return { value: (bps / 1e9).toFixed(2), unit: "Gbps" };
  if (bps >= 999_995) return { value: (bps / 1e6).toFixed(2), unit: "Mbps" };
  if (bps >= 999.5) return { value: (bps / 1e3).toFixed(2), unit: "kbps" };
  return { value: bps.toFixed(0), unit: "bps" };
}

/** A value exactly as a source printed it. */
export interface PrintedValue {
  /** The digits as printed: "2.40", not 2.4. */
  printed: string;
  unit: string;
  /** e.g. "about", "average", "up to", ">" -- as the source qualifies it. */
  qualifier?: string | null;
  /** A spread as printed, rendered as "± sd". */
  sd?: string | null;
}

/** Render a source's value without re-rounding it. */
export function formatReported(v: PrintedValue | null | undefined): string {
  if (!v) return "not reported";
  const q = v.qualifier ? `${v.qualifier} ` : "";
  const sd = v.sd ? ` ± ${v.sd}` : "";
  // ">" and "~" attach to the number; words are separated by a space.
  const joined = q === "> " || q === "~ " || q === "< " ? q.trim() : q;
  return `${joined}${v.printed}${sd} ${v.unit}`;
}
