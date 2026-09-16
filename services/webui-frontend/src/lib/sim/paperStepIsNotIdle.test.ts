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
import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import { join } from "node:path";

const HERE = new URL(".", import.meta.url).pathname;
const PAPER = readFileSync(join(HERE, "paperSim.ts"), "utf8");
const E2E = readFileSync(join(HERE, "e2eSim.ts"), "utf8");
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

  it("the cascade timeline accepts every state a simulator can report", () => {
    // It takes the status as a prop, so a narrower union than the simulator's
    // is a typecheck failure waiting for the next state to be added -- which
    // is how this was caught.
    for (const s of union(PAPER)) expect(CASCADE).toContain(`"${s}"`);
  });

  it("the head only advances while running, so stepped freezes it", () => {
    expect(CASCADE).toMatch(/if \(status !== "running"/);
  });
});
