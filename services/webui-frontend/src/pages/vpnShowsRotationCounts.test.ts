/**
 * /vpn said checklist row 2.14 (PPK rotations over a window) was read from it,
 * while nothing on the page fetched `/api/vpn/ppk-rotations`, the only
 * endpoint that serves those counts. Its header also swapped rows 2.3 and 2.11.
 */
import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import { join } from "node:path";

const HERE = new URL(".", import.meta.url).pathname;
const SRC = readFileSync(join(HERE, "VpnProtocols.tsx"), "utf8");

describe("row 2.14's counts are on the page", () => {
  it("fetches the rotations endpoint over the row's ten-minute window", () => {
    expect(SRC).toContain("/api/vpn/ppk-rotations?window_s=${ROTATION_WINDOW_S}");
    expect(SRC).toMatch(/const ROTATION_WINDOW_S = 600;/);
  });

  it("renders every count the endpoint returns, absent as a dash", () => {
    for (const f of ["v.count", "v.distinct_ids", "v.ppk_applied", "v.auth_failed"]) {
      expect(SRC).toContain(`n(${f})`);
    }
    expect(SRC).toMatch(/x == null \? "—"/);
  });

  it("puts them in the export", () => {
    expect(SRC).toContain("ppk_rotations: rotations");
  });

  it("shows the endpoint's own statement of what it does not establish", () => {
    expect(SRC).toContain("{r.note}");
  });
});

describe("the header names the rows correctly", () => {
  it("2.3 is PPK on both ends and 2.11 is ESP counters", () => {
    expect(SRC).toContain("2.3 PPK required on both ends, 2.11 ESP counters");
    expect(SRC).not.toContain("2.3 ESP counters, 2.11 PPK on both ends");
  });

  it("no longer claims row 2.14 is in /api/vpn/protocols", () => {
    expect(SRC).not.toContain("Everything those rows assert is now on\n * this page and in `curl /api/vpn/protocols`");
    expect(SRC).toContain("`curl /api/vpn/ppk-rotations`");
  });

  it("does not state a fixed rotation period", () => {
    expect(SRC).not.toContain("The lanes rotate every 30 s");
  });
});
