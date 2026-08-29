/**
 * How /verify renders the key-rate cross-check.
 *
 * The endpoint used to return `same_order_of_magnitude: boolean`. One `false`
 * meant five different things, and this page turned all five into the single
 * word "review":
 *
 *   TNO engine never ran      -> review
 *   ran, disagreed by 1000x   -> review
 *   ran, returned exactly 0   -> review
 *   BOTH returned exactly 0   -> review     <-- complete agreement
 *   ours 0, TNO 1e-09         -> review
 *
 * The fourth is the one that mattered. Two independent implementations
 * concluding that no extractable key exists at this distance is the strongest
 * agreement they can reach, and it rendered as the same "review" as the engine
 * not being installed. It is reachable with the shipped config on any link past
 * 253.51 km, and the distance field on /physics is unbounded.
 *
 * `ok` drives the colour in Verification.tsx's Row: true green, false amber,
 * undefined neutral. NEITHER_KEY is deliberately `undefined`, not `true` --
 * the implementations do agree, but painting "no key is extractable" green
 * would swap one misreading for another.
 */
export type CrosscheckVerdict =
  | "agree"
  | "disagree"
  | "neither_predicts_a_key"
  | "one_side_zero"
  | "engine_unavailable";

export interface VerdictDisplay {
  label: string;
  ok?: boolean;
  /** Shown under the table, so the reader knows what to do about it. */
  detail: string;
}

export const VERDICT_DISPLAY: Record<CrosscheckVerdict, VerdictDisplay> = {
  agree: {
    // States the band, because the band is wide. This label used to read
    // "YES (independent agreement)" while the row above it showed
    // "Relative Delta 270.7 %" -- measured on the deployed build at the
    // shipped config, where ours = 1.233e-2 and TNO = 4.573e-2, a ratio of
    // 3.71. "Agreement" is a fair word for what the check establishes (both
    // engines find a key, same order of magnitude) and an unfair one for what
    // a reader takes from it (the two numbers matched). The `disagree` label
    // below already names its threshold; this one hid the same threshold, so
    // the pair was asymmetric in exactly the direction that flatters.
    label: "YES (rates within 10x)",
    ok: true,
    detail:
      "Both implementations predict an extractable key and the two rates are "
      + "within a factor of 10. That is an order-of-magnitude check, not a "
      + "numerical match: they differ because TNO optimises the intensity mu "
      + "while the closed form uses the configured mu.",
  },
  disagree: {
    label: "NO (rates differ by more than 10x)",
    ok: false,
    detail:
      "Both implementations predict a key, but the rates are more than a factor "
      + "of 10 apart. That is a real disagreement between two independent "
      + "models, not a display artefact -- compare the parameters on /physics.",
  },
  neither_predicts_a_key: {
    label: "Both predict no extractable key",
    detail:
      "The closed form and the TNO optimiser both return exactly zero at this "
      + "distance, which is agreement, not a failure to compare. No ratio is "
      + "reported because 0/0 has none. Shorten the link on /physics to get a "
      + "rate comparison.",
  },
  one_side_zero: {
    label: "Not comparable (one side is zero)",
    ok: false,
    detail:
      "Exactly one implementation predicts an extractable key. The ratio is "
      + "undefined, and the disagreement is qualitative rather than numeric: "
      + "the two models put the zero-rate distance in different places.",
  },
  engine_unavailable: {
    label: "Not run (TNO engine unavailable)",
    detail:
      "The TNO optimiser produced no rate, so there is nothing to cross-check "
      + "against. This is an absent measurement, not a negative result -- see "
      + "the error field in the export.",
  },
};

/**
 * Resolve a verdict for display, tolerating a value the frontend has not been
 * taught yet.
 *
 * A deploy that ships a new backend against a cached bundle must not render
 * `undefined`, and must not fall through to a green "agree" either. An
 * unrecognised verdict is an absent measurement.
 */
export function describeVerdict(v: unknown): VerdictDisplay {
  // `hasOwnProperty`, not `in`. `"toString" in VERDICT_DISPLAY` is true via the
  // prototype chain, so the `in` form returned Object.prototype.toString here
  // and the page rendered "[object Object]" with an undefined colour. Caught by
  // the prototype-chain case in crosscheckVerdict.test.ts.
  if (typeof v === "string" && Object.prototype.hasOwnProperty.call(VERDICT_DISPLAY, v)) {
    return VERDICT_DISPLAY[v as CrosscheckVerdict];
  }
  return {
    label: v == null ? "Not reported" : `Unrecognised verdict: ${String(v)}`,
    detail:
      "This build does not know how to interpret the cross-check result the "
      + "API returned. Treat it as not measured.",
  };
}
