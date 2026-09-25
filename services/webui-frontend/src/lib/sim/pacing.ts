/**
 * UI pacing shared by the three client-side simulators (/e2e, /paper-flow,
 * /protocol-lab).
 *
 * Each runs a `setInterval` loop at LOOP_TICK_MS and advances a phase once the
 * phase has dwelt its nominal time. A phase can only advance ON a tick, so a
 * nominal that is not a whole number of ticks is never the dwell a foreground
 * run actually gets: 450 ms advanced on the fifth tick, at 500 ms, and every
 * exported `nominal_dwell_ms` understated the real dwell by 11-20 %. A reader
 * told to compare `ui_dwell_ms` with the nominal to spot a throttled hidden
 * tab then saw every foreground run "throttled".
 *
 * So each simulator states its dwell in ticks, and `dwellDone` compares with
 * half a tick of tolerance: timer jitter of a few milliseconds either side of
 * the tick cannot move the advance to the next tick, and the exported nominal
 * is the dwell a foreground run really has.
 */

/** The simulators' loop interval. */
export const LOOP_TICK_MS = 100;

/** A dwell of `ticks` loop ticks, in milliseconds. */
export function dwellMs(ticks: number): number {
  return ticks * LOOP_TICK_MS;
}

/** True once `elapsedMs` has reached `nominalMs` on the loop's tick grid. */
export function dwellDone(elapsedMs: number, nominalMs: number): boolean {
  return elapsedMs >= nominalMs - LOOP_TICK_MS / 2;
}
