/**
 * The cascade head must not advance while the simulation is stopped.
 *
 * `FailureCascadeTimeline` drove its head from a bare 500 ms wall-clock
 * ticker:
 *
 *     const [now, setNow] = useState(Date.now() / 1000);
 *     useEffect(() => {
 *       const t = setInterval(() => setNow(Date.now() / 1000), 500);
 *       return () => clearInterval(t);
 *     }, []);
 *     const tElapsed = startedAt ? Math.min(max, now - startedAt) : 0;
 *
 * with no reference to the run state. The `fired` flags on each cascade event
 * do NOT advance that way -- they are recomputed only inside
 * `PaperSim.snapshot()`, which runs while the simulation runs. So a paused
 * page showed the head walking past markers that stayed dashed grey: elapsed
 * simulation time that had not elapsed.
 *
 * Measured on the deployed build, /paper-flow, qkd failure injected then
 * paused, before this change:
 *
 *     status: paused   t = 14.4s -> 28.4s -> 57.4s, no interaction
 *     status: paused   t = 257.4s, and the 180s and 240s markers still carry
 *                      stroke-dasharray "2 3" -- unfired. Only 0s is solid.
 *
 * The second line is the one that establishes the defect's consequence, and it
 * needed the wait: the first cascade event after t=0 is at 180s, so every
 * observation below that threshold shows a drifting clock without yet showing
 * it overtake anything. An earlier version of this comment asserted the
 * overtaking from the 21.6 -> 28.6 pair alone, which could not support it.
 *
 * This file asserts the source shape rather than mounting React, matching how
 * the other component guards in this suite work. The property it pins is
 * narrow and mechanical: the ticker must be gated on the run state, and the
 * elapsed value must be accumulated rather than recomputed from wall clock.
 */
import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import { join } from "node:path";

const HERE = new URL(".", import.meta.url).pathname;
const SRC = readFileSync(join(HERE, "FailureCascadeTimeline.tsx"), "utf8");
const PAGE = readFileSync(
  join(HERE, "../pages/PaperDataExchange.tsx"), "utf8");

describe("the cascade head is gated on the run state", () => {
  it("the component takes the simulation status", () => {
    expect(SRC).toMatch(/status:\s*"idle"\s*\|\s*"running"\s*\|\s*"paused"/);
    expect(SRC).toContain("activeLayer, startedAt, events, status,");
  });

  it("the ticker does nothing unless the simulation is running", () => {
    expect(SRC).toMatch(/if \(status !== "running"/);
    // The interval must be created AFTER that guard, not before it.
    const guard = SRC.indexOf('status !== "running"');
    const timer = SRC.indexOf("setInterval");
    expect(guard).toBeGreaterThan(-1);
    expect(timer).toBeGreaterThan(guard);
  });

  it("the effect re-runs when the status changes", () => {
    // Without `status` in the dependency array the guard is evaluated once on
    // mount and a later pause never tears the interval down.
    expect(SRC).toMatch(/\}, \[status, startedAt\]\)/);
  });

  it("elapsed time is accumulated, not derived from the wall clock", () => {
    // `now - startedAt` counts the time the simulation spent paused, which is
    // the whole defect. It must not come back.
    expect(SRC, "elapsed is computed from wall clock again")
      .not.toMatch(/Math\.min\(max,\s*now - startedAt\)/);
    expect(SRC).toMatch(/setElapsed\(\(e\) => e \+ /);
  });

  it("resuming does not credit the time spent paused", () => {
    // lastTick must be cleared when the ticker stops, or the first tick after
    // a resume adds the whole gap in one step.
    expect(SRC).toMatch(/lastTick\.current = null/);
  });

  it("a new injection restarts the cascade clock", () => {
    expect(SRC).toMatch(/setElapsed\(0\)/);
  });
});

describe("the page supplies the status", () => {
  it("passes it to the timeline", () => {
    expect(PAGE).toMatch(/<FailureCascadeTimeline\s+status=\{status\}/);
  });
});
