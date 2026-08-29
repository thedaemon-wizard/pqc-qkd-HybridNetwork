/**
 * Two /e2e cards that reported the wrong thing, both seen in the browser.
 *
 * 1. STEPPING FROM IDLE LEFT THE BADGE READING `idle`.
 *
 *    On the deployed build, one press of Step from a fresh page moved
 *    `Active phase` to 2 and ticked phase 1 complete -- while the badge still
 *    said `status: idle`. The machine had advanced and the page said nothing
 *    had happened.
 *
 *    `step()` deliberately did not set `paused`, and the reason was sound:
 *    `paused` is the FATALITY verdict in this machine, and five assertions in
 *    `e2eFailure.test.ts` distinguish survived-from-halted by comparing
 *    against it. Reusing it would make "the operator stepped" and "the run
 *    died" the same state.
 *
 *    So the fix is the one the old comment said was needed -- a distinct
 *    value -- not a reuse of an overloaded one.
 *
 * 2. THROUGHPUT SHOWED A MEASURED-LOOKING ZERO.
 *
 *    After that same step the card read "Throughput (bps) 0" beside "Packets
 *    encrypted 0". Before the step it correctly read "Throughput (not
 *    reported) —".
 *
 *    `rate_bps` was a non-optional `number` initialised to 0, and `formatRate`
 *    renders a dash only for a non-finite value. A measured zero is
 *    unreachable here: the assignment divides a byte count that is positive
 *    only when packets were encrypted, by a positive elapsed time. Every 0 the
 *    field could show was an absence wearing the shape of a measurement.
 */
import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { E2ESim, type E2EState } from "./e2eSim";

const HERE = new URL(".", import.meta.url).pathname;
const SIM = readFileSync(join(HERE, "e2eSim.ts"), "utf8");

/** The suite's existing idiom: state arrives through the callback. */
function sim(): { s: E2ESim; last: () => E2EState } {
  let seen: E2EState | null = null;
  const s = new E2ESim((st) => { seen = st; });
  s.reset();          // the callback only fires on emit(); seed the state
  return { s, last: () => seen as E2EState };
}

describe("a manual step is distinguishable from doing nothing", () => {
  it("stepping from idle does not leave the status at idle", () => {
    const { s, last } = sim();
    expect(last().status).toBe("idle");
    s.step();
    expect(last().status, "the badge still reads idle after a step")
      .not.toBe("idle");
  });

  it("and the machine really did advance, so the badge was wrong before", () => {
    const { s, last } = sim();
    s.step();
    expect(last().current_phase).toBeGreaterThan(0);
  });

  it("a step is not reported as a pause", () => {
    // `paused` is the fatality verdict. If a manual step set it, every test
    // that reads survived-vs-halted from the status would start lying.
    const { s, last } = sim();
    s.step();
    expect(last().status).toBe("stepped");
  });

  it("stepping while running is still refused", () => {
    // Asserted on the guard rather than by calling start(): start() installs a
    // window.setInterval, and these tests run in the node environment the rest
    // of this directory uses -- e2eFailure.test.ts drives the machine with
    // step() for the same reason.
    expect(SIM).toMatch(/step\(\) \{\s*if \(this\.s\.status === "running"\) return;/);
  });
});

describe("the fatality verdict survives a step", () => {
  it("`paused` still means halted, not stepped", () => {
    // The whole reason `stepped` exists. If a step that kills the run
    // relabelled it, a fatal injection would read as a manual advance.
    expect(SIM).toMatch(/status: "idle" \| "running" \| "paused" \| "stepped"/);
    expect(SIM, "step() sets paused again").not.toMatch(
      /step\(\)[\s\S]{0,400}this\.s\.status = "paused";/);
  });
});

describe("throughput distinguishes absent from zero", () => {
  it("is null before anything has been measured", () => {
    expect(sim().last().rate_bps).toBeNull();
  });

  it("is still null after a step that encrypts nothing", () => {
    const { s, last } = sim();
    s.step();
    const snap = last();
    if (snap.total_packets === 0) {
      expect(snap.rate_bps,
        "0 packets with a 0 bps rate is an absence rendered as a measurement")
        .toBeNull();
    }
  });

  it("the field is nullable in the type, not a number defaulted to 0", () => {
    expect(SIM).toMatch(/rate_bps: number \| null;/);
    expect(SIM, "re-initialised to 0").not.toMatch(/rate_bps: 0,/);
  });

  it("a real measurement is still reported", () => {
    // Not vacuous: every assertion above would pass on a field that is always
    // null. Step through complete cycles -- step() is refused while running,
    // so this drives the machine manually rather than starting it -- and
    // require a positive rate once packets exist.
    const { s, last } = sim();
    for (let i = 0; i < 24; i++) s.step();
    const snap = last();
    expect(snap.total_packets,
      "no packets were encrypted, so this test proves nothing about a real rate")
      .toBeGreaterThan(0);
    expect(typeof snap.rate_bps).toBe("number");
    expect(snap.rate_bps as number).toBeGreaterThan(0);
  });
});
