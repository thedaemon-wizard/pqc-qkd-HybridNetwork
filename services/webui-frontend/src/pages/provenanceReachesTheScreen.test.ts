/**
 * What the service already admits must reach the reader.
 *
 * `/api/stats` has published `last_round_synthetic`, `skr_provenance` and
 * `modelled_skr_bps` for a long time, and `skr_reflects_current_config` since
 * the config-generation change. `/benchmarks` plotted the numbers and threw all
 * four away, so a synthetic round from a possibly-stale model rendered exactly
 * like a measurement.
 *
 * Measured on the live demo 2026-08-28:
 *
 *     alice: rounds=36 accepted=36 synthetic=true current=true
 *     bob:   rounds=6  accepted=6  synthetic=true current=true
 *
 * Two things follow. The page read `s?.alice` with no label, so it charted one
 * of two diverging nodes without saying which -- a 6x difference in rounds. And
 * `synthetic: true` never appeared anywhere, on a page whose whole purpose is to
 * show what the simulator measured.
 *
 * The export was worse than the screen: four arrays, no node, no backend, no
 * timestamp, no provenance -- offered as a citable artefact.
 *
 * Also covered here, from the same sweep:
 *  - `/console` rendered raw ANSI SGR codes as visible text, and carried them
 *    into the exported log.
 *  - `/hil` lost four spaces to JSX text-node trimming, in the four lines a
 *    reader copy-pastes.
 */
import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { stripAnsi } from "./Console";

const HERE = new URL(".", import.meta.url).pathname;
const src = (p: string) => readFileSync(join(HERE, p), "utf8");

const BENCH = src("Benchmarks.tsx");
const HIL = src("HIL.tsx");

// --------------------------------------------------------------------------
// /benchmarks names its node and its provenance.
// --------------------------------------------------------------------------

describe("/benchmarks says which node it is plotting", () => {
  it("the node is a named constant, not an inline property access", () => {
    expect(BENCH).toContain('const BENCH_NODE = "alice"');
    expect(BENCH, "the node is still read inline, so it cannot be labelled")
      .not.toMatch(/s\?\.alice\s*\?\?/);
  });

  it("the node appears on screen and in the export", () => {
    expect(BENCH).toMatch(/Counters for <b>\{BENCH_NODE\}<\/b>/);
    expect(BENCH).toMatch(/node:\s*BENCH_NODE/);
  });
});

describe("/benchmarks surfaces what the service already admits", () => {
  it.each([
    "last_round_synthetic",
    "skr_provenance",
    "modelled_skr_bps",
    "skr_reflects_current_config",
  ])("%s reaches the export", (field) => {
    expect(BENCH).toContain(field);
  });

  it("a synthetic round is called out on screen, not only in the export", () => {
    expect(BENCH).toMatch(/prov\.synthetic === true/);
    expect(BENCH).toMatch(/SIMULATED, not measured/);
  });

  it("a stale rate is called out on screen", () => {
    expect(BENCH).toMatch(/prov\.current === false/);
    expect(BENCH).toMatch(/predates the current parameters/);
  });

  it("the three-state fields are read as tri-state, not coerced", () => {
    // `?? false` would turn "the KME did not answer" into "not synthetic",
    // which is the substitution this page's own comments reject for QBER.
    expect(BENCH).toMatch(/typeof a\.last_round_synthetic === "boolean"/);
    expect(BENCH).toMatch(/typeof a\.skr_reflects_current_config === "boolean"/);
  });
});

// --------------------------------------------------------------------------
// /console strips ANSI before render AND before export.
// --------------------------------------------------------------------------

describe("the container log is readable", () => {
  it("strips the escapes the live endpoint really returns", () => {
    // Verbatim from GET /api/logs/alice on the public demo.
    const raw = "[INFO] \x1b[36mPRIMARY[1]\x1b[0m [OK] HKDF derivation completed";
    expect(stripAnsi(raw))
      .toBe("[INFO] PRIMARY[1] [OK] HKDF derivation completed");
  });

  it("leaves ordinary text alone", () => {
    const plain = "2026/08/28 04:38:54 [INFO] PSK configured on wg0";
    expect(stripAnsi(plain)).toBe(plain);
  });

  it("handles multiple codes on one line and multi-line input", () => {
    expect(stripAnsi("\x1b[1m\x1b[31mA\x1b[0m\n\x1b[36mB\x1b[0m")).toBe("A\nB");
  });

  it("is applied on arrival, so the render and the export share it", () => {
    // Stripping at only one of the two would leave the other carrying escapes,
    // and the export is the one offered as evidence.
    expect(src("Console.tsx")).toMatch(/setLog\(stripAnsi\(/);
  });
});

// --------------------------------------------------------------------------
// /hil instructions survive JSX text trimming.
// --------------------------------------------------------------------------

describe("the /hil setup steps are copy-pasteable", () => {
  it("no </code> or </b> is followed by a newline with no space", () => {
    // JSX drops the newline + indentation between an element and the text that
    // follows, so `</code>\n  in .env` renders as `</code>in .env`.
    const offenders: string[] = [];
    const lines = HIL.split("\n");
    for (let i = 0; i < lines.length - 1; i++) {
      const ends = /<\/(code|b)>$/.test(lines[i].trimEnd());
      const nextIsWord = /^\s+[a-z<]/.test(lines[i + 1]);
      if (ends && nextIsWord) offenders.push(`HIL.tsx:${i + 1}`);
    }
    expect(offenders, "these will render with the space missing").toEqual([]);
  });

  it("the four known sites carry an explicit space", () => {
    expect((HIL.match(/\{" "\}/g) ?? []).length).toBeGreaterThanOrEqual(4);
  });
});
