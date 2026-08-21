/**
 * Knocking out a layer on `/e2e` must depend on the mode.
 *
 * `/paper-flow` models failure as a cascade down a multi-hop chain, which is
 * what its paper describes. `/e2e` is a single tunnel: there is nothing to
 * cascade through, and copying the cascade UI would have produced a control
 * that looked meaningful and measured nothing.
 *
 * What is worth showing here is the claim the whole project rests on. In mode
 * C the QKD and PQC legs are combined, so losing one leaves the other and the
 * run degrades rather than stops. In modes A and B there is only one source,
 * so the same injection is fatal. If that asymmetry ever collapses -- if a
 * hybrid run starts dying like a single-source run, or a single-source run
 * starts surviving with no key material -- the page is no longer demonstrating
 * anything, and these tests fail.
 */
import { describe, expect, it } from "vitest";

import { E2ESim, type E2EState } from "./e2eSim";

/** Drive a sim without timers: step through whole cycles and return the state. */
function runCycles(mode: "A" | "B" | "C", inject: "qkd" | "pqc" | "data" | null, steps: number) {
  let last: E2EState | null = null;
  const sim = new E2ESim((s) => { last = s; });
  sim.setMode(mode);
  if (inject) sim.injectFailure(inject);
  // No stop() call: step() drives the machine directly and starts no timer, so
  // there is nothing running to tear down. An earlier `sim.stop?.()` here type-
  // checked as an error while passing at runtime, because optional chaining
  // silently tolerates the missing method.
  for (let i = 0; i < steps; i++) sim.step();
  return { sim, state: last as unknown as E2EState };
}

const PHASES_PER_CYCLE = 4;

describe("mode C survives one leg failing", () => {
  it("keeps encrypting when the QKD layer is knocked out", () => {
    const { state } = runCycles("C", "qkd", PHASES_PER_CYCLE);
    expect(state.failed_layer).toBe("qkd");
    expect(state.status).not.toBe("paused");
    expect(state.total_packets).toBeGreaterThan(0);
  });

  it("keeps encrypting when the PQC layer is knocked out", () => {
    const { state } = runCycles("C", "pqc", PHASES_PER_CYCLE);
    expect(state.failed_layer).toBe("pqc");
    expect(state.total_packets).toBeGreaterThan(0);
  });

  it("says it is degraded rather than reporting a clean run", () => {
    // Surviving silently would be worse than failing: the operator would read
    // a normal-looking cycle and not know a layer was gone.
    const { state } = runCycles("C", "qkd", PHASES_PER_CYCLE);
    expect(state.last_error).toMatch(/degraded/i);
    expect(state.last_error).toMatch(/qkd/i);
  });
});

describe("single-source modes cannot survive their only leg failing", () => {
  it("mode A stops when QKD fails", () => {
    const { state } = runCycles("A", "qkd", PHASES_PER_CYCLE);
    expect(state.status).toBe("paused");
    expect(state.total_packets).toBe(0);
    expect(state.last_error).toMatch(/no other key source/i);
  });

  it("mode B stops when PQC fails", () => {
    const { state } = runCycles("B", "pqc", PHASES_PER_CYCLE);
    expect(state.status).toBe("paused");
    expect(state.total_packets).toBe(0);
  });

  it("mode A is unaffected by a PQC failure it never used", () => {
    // The converse matters too: failing a layer a mode does not use must not
    // stop it, or the control is just a global kill switch.
    const { state } = runCycles("A", "pqc", PHASES_PER_CYCLE);
    expect(state.status).not.toBe("paused");
    expect(state.total_packets).toBeGreaterThan(0);
  });

  it("mode B is unaffected by a QKD failure it never used", () => {
    const { state } = runCycles("B", "qkd", PHASES_PER_CYCLE);
    expect(state.status).not.toBe("paused");
    expect(state.total_packets).toBeGreaterThan(0);
  });
});

describe("the data layer has no fallback in any mode", () => {
  it.each(["A", "B", "C"] as const)("mode %s stops when the data layer fails", (mode) => {
    const { state } = runCycles(mode, "data", PHASES_PER_CYCLE);
    expect(state.status).toBe("paused");
    expect(state.total_packets).toBe(0);
    expect(state.last_error).toMatch(/AEAD/);
  });
});

describe("clearing a failure", () => {
  it("restores normal operation", () => {
    let last: E2EState | null = null;
    const sim = new E2ESim((s) => { last = s; });
    sim.setMode("A");
    sim.injectFailure("qkd");
    for (let i = 0; i < PHASES_PER_CYCLE; i++) sim.step();
    expect((last as unknown as E2EState).status).toBe("paused");

    sim.clearFailure();
    sim.reset();
    for (let i = 0; i < PHASES_PER_CYCLE; i++) sim.step();
    const after = last as unknown as E2EState;
    expect(after.failed_layer).toBeNull();
    expect(after.total_packets).toBeGreaterThan(0);
  });

  it("leaves no failure set on a fresh simulator", () => {
    const { state } = runCycles("C", null, 1);
    expect(state.failed_layer).toBeNull();
  });
});

describe("a run with no injection is unaffected", () => {
  it("completes a cycle and reports no error", () => {
    const { state } = runCycles("C", null, PHASES_PER_CYCLE);
    expect(state.failed_layer).toBeNull();
    expect(state.last_error).toBe("");
    expect(state.total_packets).toBeGreaterThan(0);
    expect(state.completed_cycles).toBe(1);
  });
});
