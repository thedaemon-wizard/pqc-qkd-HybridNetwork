/**
 * When no key material survives, the page must not print a PSK prefix.
 *
 * Phase 3 ran `deriveHkdfSha3(qkdKey, pqcSecret, mode)` unconditionally, on the
 * stated reasoning that "with one leg gone the PSK is weaker, not absent". True
 * for the seven cells where one leg survives. In two of the nine mode x failure
 * cells BOTH legs are empty, and there the reasoning does not hold:
 *
 *   mode A (QKD-only) with the QKD layer down  -> qkdKey empty, pqcSecret empty
 *   mode B (PQC-only) with the PQC layer down  -> qkdKey empty, pqcSecret empty
 *
 * HKDF over a zero-length IKM does not fail. It returns a value fixed entirely
 * by the public salt ("pqcqkd-e2e") and info ("mode-A"/"mode-B"), identical on
 * every run and on every machine. The page rendered its first eight hex digits
 * under the heading "Latest derived WireGuard PSK (HKDF-SHA3-256)", and the
 * text export wrote it to `# psk_prefix:`. A public constant with zero entropy,
 * displayed in the slot the UI labels key material.
 *
 * Both cells are fatal at phase 4, so the run stops immediately afterwards --
 * which is why this was easy to miss: the prefix appeared for one phase, looked
 * like a hex key, and was gone. Nothing in the build could contradict it.
 *
 * The tests below pin three separate things, because fixing only the display
 * would leave the other two free to drift:
 *   1. the empty-IKM derivation really is a constant (measured, not assumed);
 *   2. exactly those two cells reach it, named explicitly;
 *   3. those two cells are exactly the fatal ones, so no surviving run is left
 *      holding an empty `derived` for the phase-4 AEAD.
 */
import { describe, expect, it } from "vitest";

import { deriveHkdfSha3 } from "./crypto";
import { E2ESim, type E2ELayer, type E2EState, type Mode } from "./e2eSim";

const MODES: Mode[] = ["A", "B", "C"];
const LAYERS: E2ELayer[] = ["qkd", "pqc", "data"];
const PHASES_PER_CYCLE = 4;

function hex(b: Uint8Array): string {
  return Array.from(b).map((x) => x.toString(16).padStart(2, "0")).join("");
}

/** Run one cycle and hand back the final state plus phase 3's detail. */
function cycle(mode: Mode, inject: E2ELayer | null) {
  let last: E2EState | null = null;
  const sim = new E2ESim((s) => { last = s; });
  sim.setMode(mode);
  if (inject) sim.injectFailure(inject);
  for (let i = 0; i < PHASES_PER_CYCLE; i++) sim.step();
  const state = last as unknown as E2EState;
  const p3 = state.history.find((h) => h.phase === 3);
  return { state, detail: (p3?.detail ?? {}) as Record<string, unknown> };
}

describe("HKDF over an empty IKM is a public constant, not a key", () => {
  it("returns the same bytes every time, so it carries no entropy", () => {
    const empty = new Uint8Array(0);
    for (const mode of MODES) {
      const a = deriveHkdfSha3(empty, empty, mode);
      const b = deriveHkdfSha3(empty, empty, mode);
      expect(hex(a)).toBe(hex(b));
      expect(a.length).toBe(32);
    }
    // Distinct per mode only because `info` differs -- which is exactly the
    // point: everything that varies is public.
    expect(hex(deriveHkdfSha3(empty, empty, "A")))
      .not.toBe(hex(deriveHkdfSha3(empty, empty, "B")));
  });
});

describe("the two cells where nothing survives", () => {
  it("is exactly mode A with QKD down and mode B with PQC down", () => {
    const starved: string[] = [];
    for (const mode of MODES) {
      for (const layer of LAYERS) {
        const { detail } = cycle(mode, layer);
        if (detail.qkd_bytes === 0 && detail.pqc_bytes === 0) {
          starved.push(`${mode}/${layer}`);
        }
      }
    }
    // Named rather than counted. A count would still pass if the set moved.
    expect(starved.sort()).toEqual(["A/qkd", "B/pqc"]);
  });

  it("reports no PSK prefix instead of the constant", () => {
    for (const [mode, layer] of [["A", "qkd"], ["B", "pqc"]] as const) {
      const { state, detail } = cycle(mode, layer);
      const constant = hex(deriveHkdfSha3(new Uint8Array(0), new Uint8Array(0), mode))
        .slice(0, 16);

      expect(detail.psk_prefix, `${mode}/${layer} phase-3 detail`).toBeNull();
      expect(detail.psk_prefix).not.toBe(constant);
      // The UI renders `last_psk_prefix_hex || "—"`, so empty is the em dash.
      expect(state.last_psk_prefix_hex, `${mode}/${layer} displayed prefix`).toBe("");
      // "we looked and there is nothing" must be sayable, not inferred from a
      // blank -- the same tri-state discipline the VPN endpoint needs.
      expect(String(detail.note ?? "")).toMatch(/no key material/i);
    }
  });

  it("still prints a real prefix wherever one leg survives", () => {
    const survivors: Array<[Mode, E2ELayer | null]> = [
      ["A", null], ["A", "pqc"], ["B", null], ["B", "qkd"],
      ["C", null], ["C", "qkd"], ["C", "pqc"],
    ];
    for (const [mode, layer] of survivors) {
      const { state, detail } = cycle(mode, layer);
      expect(state.last_psk_prefix_hex, `${mode}/${layer ?? "none"}`).toMatch(/^[0-9a-f]{16}$/);
      expect(detail.psk_prefix).toBe(state.last_psk_prefix_hex);
    }
  });
});

describe("no surviving run reaches phase 4 without key material", () => {
  it("the starved cells are exactly the fatal ones", () => {
    const starved: string[] = [];
    const fatal: string[] = [];
    for (const mode of MODES) {
      for (const layer of LAYERS) {
        const { state, detail } = cycle(mode, layer);
        if (detail.qkd_bytes === 0 && detail.pqc_bytes === 0) starved.push(`${mode}/${layer}`);
        if (state.failure_is_fatal) fatal.push(`${mode}/${layer}`);
      }
    }
    // `data` failures are fatal in every mode without starving the KDF, so
    // fatal is the larger set; what matters is that starved is inside it.
    for (const cell of starved) expect(fatal).toContain(cell);
  });
});
