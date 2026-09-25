/**
 * /paper-flow had the defect /e2e was already fixed for, because the fix went
 * into one simulator and not the other.
 *
 * Measured on the deployed build: one press of Step from a fresh page moved
 * `phase` from idle to 1 while the badge still read `status: idle`. The
 * machine had advanced and the page said nothing had happened.
 *
 * `paperSim.step()` set no state at all:
 *
 *     step() {
 *       if (this.status === "running") return;
 *       if (this.phase === 0) { this.beginCycle(); this.emit(); return; }
 *       this.runPhase();
 *     }
 *
 * Reusing `paused` was not available for the same reason as in e2eSim: it is
 * the halted verdict here too, so an operator stepping and a run dying would
 * read identically.
 *
 * This file also pins the SYMMETRY. The two simulators are separate classes
 * with separate status unions, and that is exactly how one of them kept a bug
 * the other had lost. If a future change teaches one of them a new state, this
 * asks why the other did not get it.
 */
import { afterAll, beforeAll, describe, expect, it } from "vitest";

import { PaperSim } from "./paperSim";
import type { PaperFlowState } from "./paperSim";

import { readFileSync } from "node:fs";
import { join } from "node:path";

const HERE = new URL(".", import.meta.url).pathname;
const PAPER = readFileSync(join(HERE, "paperSim.ts"), "utf8");
const E2E = readFileSync(join(HERE, "e2eSim.ts"), "utf8");
const LAB = readFileSync(join(HERE, "protocolLabSim.ts"), "utf8");
const CASCADE = readFileSync(
  join(HERE, "../../components/FailureCascadeTimeline.tsx"), "utf8");

describe("a manual step on /paper-flow is distinguishable from doing nothing", () => {
  it("step() sets a state rather than leaving the badge alone", () => {
    const fn = PAPER.slice(PAPER.indexOf("  step() {"));
    expect(fn.slice(0, 900)).toMatch(/this\.status = "stepped";/);
  });

  it("does not reuse the halted verdict", () => {
    const fn = PAPER.slice(PAPER.indexOf("  step() {"), PAPER.indexOf("  reset()"));
    // Anchored at the START of a line, so it catches an UNCONDITIONAL
    // assignment and not the guarded restore below it. The first version of
    // this assertion matched its own correct code: the restore line ends in
    // `this.status = "paused";` too, and a trailing-anchored pattern cannot
    // tell the two apart.
    expect(fn, "step() sets paused unconditionally, which is how a run reports that it died")
      .not.toMatch(/^\s*this\.status = "paused";/m);
  });

  it("a step from a paused run leaves it paused", () => {
    // The operator asked for one phase, not for a resume.
    const fn = PAPER.slice(PAPER.indexOf("  step() {"), PAPER.indexOf("  reset()"));
    expect(fn).toMatch(/if \(before === "paused"\) this\.status = "paused";/);
  });

  it("emits, or the page never learns the state changed", () => {
    const fn = PAPER.slice(PAPER.indexOf("  step() {"), PAPER.indexOf("  reset()"));
    expect(fn).toMatch(/this\.emit\(\)/);
  });

  it("still refuses to step while running", () => {
    expect(PAPER).toMatch(/step\(\) \{\s*if \(this\.status === "running"\) return;/);
  });
});

describe("the two simulators agree on the states they can be in", () => {
  const union = (src: string) =>
    (src.match(/status:\s*("(?:idle|running|paused|stepped)"(?:\s*\|\s*"(?:idle|running|paused|stepped)")*)/)?.[1] ?? "")
      .split("|").map((s) => s.trim().replace(/"/g, "")).sort();

  it("paperSim and e2eSim expose the same status union", () => {
    // Divergence here is what let /paper-flow keep a bug /e2e had lost.
    expect(union(PAPER)).toEqual(union(E2E));
  });

  it("protocolLabSim exposes the same union, and refuses a step while running", () => {
    // The third simulator, added for /protocol-lab. Same union, same step rule
    // and the same paused-stays-paused restore, or the badge on one page means
    // something different from the badge on the other two.
    expect(union(LAB)).toEqual(union(PAPER));
    expect(LAB).toMatch(/step\(\) \{\s*if \(this\.status === "running"\) return;/);
    const fn = LAB.slice(LAB.indexOf("  step() {"), LAB.indexOf("  reset() {"));
    expect(fn).toMatch(/this\.status = "stepped";/);
    expect(fn).toMatch(/if \(before === "paused"\) this\.status = "paused";/);
    expect(fn).not.toMatch(/^\s*this\.status = "paused";/m);
  });

  it("the cascade timeline accepts every state a simulator can report", () => {
    // It takes the status as a prop, so a narrower union than the simulator's
    // is a typecheck failure waiting for the next state to be added -- which
    // is how this was caught.
    for (const s of union(PAPER)) expect(CASCADE).toContain(`"${s}"`);
  });

  it("the head only advances while running, so stepped freezes it", () => {
    // The clock is the simulator's (cascadeHeadTracksTheRun.test.ts drives
    // it); the timeline only draws it. The tick that advances it returns
    // before doing anything unless the run is running.
    expect(CASCADE).toMatch(/Math\.min\(max, elapsedS\)/);
    const tick = PAPER.slice(PAPER.indexOf("  private tick() {"));
    expect(tick.slice(0, 200)).toMatch(/if \(this\.status !== "running"\) return;/);
    expect(tick).toContain("this.advanceCascade(");
  });
});

/**
 * Everything above reads paperSim.ts as TEXT. That is worth keeping -- it is how
 * the symmetry between the two simulators is pinned, and a source match survives
 * refactors that a behavioural test would have to be rewritten for.
 *
 * But it is not sufficient, and the docstring at the top of this file says why
 * without noticing: the defect was "measured on the deployed build". None of the
 * nine assertions above runs a single line of the simulator. `step()` could set
 * `this.status = "stepped"` exactly as matched, and a regression in
 * `beginCycle()`, `emit()` or `snapshot()` could still leave the badge reading
 * `idle` -- with every check in this file green.
 *
 * These drive the class instead. They assert on what `onState` RECEIVES rather
 * than on a private field, because that snapshot is what the page renders:
 * PaperDataExchange.tsx does `state?.status ?? "idle"`, so a status that never
 * reaches the snapshot is indistinguishable from no status at all.
 */
describe("stepping actually produces the state the page reads", () => {
  // `ensureLoop()` calls `window.setInterval`; `stopLoop()` calls the bare
  // `clearInterval`. Nothing else in the simulator touches the DOM, and no other
  // test in this suite needs a document -- so stub the two functions the loop
  // actually uses rather than switching the whole file to jsdom for four
  // assertions. The stub is scoped to this file: vitest isolates per file.
  const realWindow = (globalThis as { window?: unknown }).window;
  beforeAll(() => {
    (globalThis as { window?: unknown }).window = {
      setInterval: (fn: () => void, ms: number) => setInterval(fn, ms),
      clearInterval: (id: number) => clearInterval(id),
    };
  });
  afterAll(() => {
    if (realWindow === undefined) delete (globalThis as { window?: unknown }).window;
    else (globalThis as { window?: unknown }).window = realWindow;
  });

  function driven() {
    const seen: PaperFlowState[] = [];
    const sim = new PaperSim((s) => seen.push(s));
    return { sim, seen, last: () => seen[seen.length - 1] };
  }

  it("a step from idle emits stepped, and advances the phase with it", () => {
    const { sim, last } = driven();
    expect(last().status).toBe("idle");
    expect(last().current_phase).toBe(0);

    sim.step();

    // Both halves matter. The phase moving with the badge still reading `idle`
    // IS the original defect, so neither assertion alone reproduces it.
    expect(last().current_phase).toBe(1);
    expect(last().status).toBe("stepped");
  });

  it("a step from paused emits paused, not stepped", () => {
    const { sim, last } = driven();
    sim.start();
    sim.pause();
    expect(last().status).toBe("paused");

    sim.step();

    expect(last().status).toBe("paused");
  });

  it("a step while running emits nothing at all", () => {
    const { sim, seen } = driven();
    sim.start();
    const before = seen.length;

    sim.step();

    expect(seen.length).toBe(before);
  });

  it("reset returns the emitted state to idle", () => {
    const { sim, last } = driven();
    sim.step();
    expect(last().status).toBe("stepped");

    sim.reset();

    expect(last().status).toBe("idle");
    expect(last().current_phase).toBe(0);
  });
});
