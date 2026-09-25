/**
 * A "history" chart must record events, not polls.
 *
 * `/benchmarks` titles its charts "BB84 round latency (ms)" and "QBER history",
 * and its poll appended `a.last_qber ?? 0` every second whether or not a round
 * had happened. Three things were untrue at once:
 *
 *   * with the key pool full, rounds are infrequent -- measured on the demo,
 *     4 rounds against a 1 s poll -- so most points were the same round
 *     resampled, drawing a flat line that reads as a stuck sensor;
 *   * "Avg QBER" averaged those duplicates, making it time-weighted while
 *     presenting as per-round;
 *   * `?? 0` recorded a MISSING reading as zero, and zero is a legitimate
 *     QBER -- the simqn backend returned [0.0, 0.029412, 0.009804] over three
 *     rounds -- so a fabricated point was indistinguishable from a real one.
 *
 * The append rule is extracted here so it can be tested without a browser. The
 * page holds `lastPlottedRound` in a ref and applies exactly this.
 */
import { describe, expect, it } from "vitest";

import {
  ROUND_HISTORY_LIMIT, appendRound, benchmarksCsvRows, isNewRound, reading,
  type BenchSample, type RoundRec,
} from "./benchmarksHistory";

/**
 * Replays polls through the SAME functions the page calls.
 *
 * The first version of this file reimplemented the rule here instead. That is
 * the mistake the PRNG tests in this repository made once -- deleting a
 * coercion from the shipped class left them green, because they were asserting
 * properties of a copy. Driving the real functions is the point.
 */
function qberPoints(polls: BenchSample[]): number[] {
  const out: number[] = [];
  let lastRound: number | null = null;
  for (const p of polls) {
    if (!isNewRound(lastRound, p)) continue;
    lastRound = p.rounds_total as number;
    const q = reading(p.last_qber);
    if (q !== null) out.push(q);
  }
  return out;
}

const poll = (r: number, q?: number): BenchSample => ({ rounds_total: r, last_qber: q });

describe("the history records rounds", () => {
  it("adds nothing when a poll brings no new round", () => {
    // Ten polls, one round. The old code produced ten points.
    const polls = Array.from({ length: 10 }, () => poll(4, 0.0));
    expect(qberPoints(polls)).toEqual([0.0]);
  });

  it("adds one point per round", () => {
    expect(qberPoints([poll(1, 0.0), poll(1, 0.0), poll(2, 0.029412), poll(3, 0.009804)]))
      .toEqual([0.0, 0.029412, 0.009804]);
  });

  it("keeps a genuine zero", () => {
    // Zero is a real QBER at these sifted counts, so it must not be filtered
    // out along with the missing readings.
    expect(qberPoints([poll(1, 0.0)])).toEqual([0.0]);
  });

  it("drops a round whose reading is missing rather than calling it zero", () => {
    expect(qberPoints([poll(1, 0.02), { rounds_total: 2 }, poll(3, 0.01)]))
      .toEqual([0.02, 0.01]);
  });

  it("ignores a poll with no round counter at all", () => {
    expect(qberPoints([{ last_qber: 0.5 }, poll(1, 0.02)])).toEqual([0.02]);
  });
});

describe("what the average means", () => {
  it("is per round, not per second", () => {
    // One round at 0.10 that persists for nine polls, then one at 0.02.
    // Polling gives (0.10 x 9 + 0.02)/10 = 0.092; per round it is 0.06.
    const polls = [...Array.from({ length: 9 }, () => poll(1, 0.10)), poll(2, 0.02)];
    const pts = qberPoints(polls);
    const mean = pts.reduce((a, b) => a + b, 0) / pts.length;
    expect(pts).toEqual([0.10, 0.02]);
    expect(mean).toBeCloseTo(0.06, 10);
    expect(mean).not.toBeCloseTo(0.092, 3);
  });
});

describe("the CSV pairs each round's readings with each other", () => {
  it("keeps latency and QBER of one round on one row, even when a reading is missing", () => {
    // Round 11 has no latency. Zipping two separate arrays by position put
    // round 12's latency beside round 11's QBER from here on.
    let h: RoundRec[] = [];
    h = appendRound(h, { round: 10, ms: 220, qber: 0.01 });
    h = appendRound(h, { round: 11, ms: null, qber: 0.02 });
    h = appendRound(h, { round: 12, ms: 300, qber: 0.03 });
    expect(benchmarksCsvRows(h)).toEqual([
      { round: 10, round_ms: 220, qber: 0.01 },
      { round: 11, round_ms: null, qber: 0.02 },
      { round: 12, round_ms: 300, qber: 0.03 },
    ]);
  });

  it("keeps the last ROUND_HISTORY_LIMIT rounds", () => {
    let h: RoundRec[] = [];
    for (let i = 0; i < ROUND_HISTORY_LIMIT + 7; i++) h = appendRound(h, { round: i, ms: i, qber: 0 });
    expect(h).toHaveLength(ROUND_HISTORY_LIMIT);
    expect(h[0].round).toBe(7);
  });
});
