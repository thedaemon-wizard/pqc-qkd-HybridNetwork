/**
 * When a benchmarks poll should add a point, and what it may add.
 *
 * Extracted from `pages/Benchmarks.tsx` so the rule is testable and so the
 * test exercises the code the page runs. An earlier draft of the test
 * reimplemented this logic beside it, which is the same mistake the PRNG tests
 * in this repository made once: asserting properties of a reference copy while
 * the shipped code drifted.
 */

/** The subset of `/api/stats`'s `alice` object this page reads. */
export interface BenchSample {
  rounds_total?: number;
  last_qber?: number;
  last_round_ms?: number;
}

/**
 * True when this poll represents a round not yet plotted.
 *
 * The page appended on every tick regardless. With the key pool full, rounds
 * are infrequent -- measured on the demo, 4 rounds against a 1 s poll -- so the
 * charts titled "round latency" and "QBER history" were histories of POLLS,
 * mostly the same round resampled, drawing a flat line that reads as a stuck
 * sensor. It also made "Avg QBER" time-weighted while presenting as per-round.
 */
export function isNewRound(previous: number | null, s: BenchSample): boolean {
  return typeof s.rounds_total === "number" && s.rounds_total !== previous;
}

/**
 * The reading to plot, or null to plot nothing for this round.
 *
 * Deliberately not `value ?? 0`. Zero is a legitimate QBER at these sifted
 * counts -- the simqn backend returned [0.0, 0.029412, 0.009804] over three
 * rounds -- so substituting zero for a MISSING reading makes a fabricated
 * point indistinguishable from a real one.
 */
export function reading(value: number | undefined): number | null {
  return typeof value === "number" ? value : null;
}

/** One KME round as plotted and exported: both readings belong to `round`. */
export interface RoundRec {
  round: number;
  ms: number | null;
  qber: number | null;
}

/** Rounds kept for the charts and the export. */
export const ROUND_HISTORY_LIMIT = 120;

/**
 * Append one round, keeping the last ROUND_HISTORY_LIMIT.
 *
 * One array keyed by round, because two did not line up: latency and QBER were
 * kept in separate arrays, each appended only when its own reading was present,
 * and the CSV zipped them by position. After a round with one reading missing,
 * every later row paired the latency of one round with the QBER of another.
 */
export function appendRound(h: RoundRec[], r: RoundRec): RoundRec[] {
  return [...h, r].slice(-ROUND_HISTORY_LIMIT);
}

/** CSV rows: each row's round_ms and qber come from the same round. */
export function benchmarksCsvRows(h: RoundRec[]): Record<string, unknown>[] {
  return h.map((r) => ({ round: r.round, round_ms: r.ms, qber: r.qber }));
}
