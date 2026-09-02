/**
 * An exported artefact must say which build produced it.
 *
 * The export store is a rolling window and keeps files made by older builds. A
 * JSON saved in June 2026 still carries `dual_path` -- a `PaperSim` field that
 * was deleted this round because nothing in the UI could set it. Someone
 * opening that artefact today sees a key the current build never writes, with
 * nothing in the file to say which build wrote it.
 *
 * That is history, not a defect, and the version number is what makes it
 * legible as history. Verified against the deployed store: 48 artefacts across
 * five formats, the oldest from 2026-06-14, none of them versioned.
 *
 * The stamp is applied inside `downloadJSON` rather than at each call site, so
 * that no page can forget it and no two pages can disagree about the number.
 */
import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import { join } from "node:path";

const HERE = new URL(".", import.meta.url).pathname;
const SRC = readFileSync(join(HERE, "../exporters.ts"), "utf8");

describe("JSON exports are versioned", () => {
  it("declares a single version constant", () => {
    expect(SRC).toMatch(/export const EXPORT_SCHEMA_VERSION = \d+;/);
  });

  it("stamps inside downloadJSON, not at the call sites", () => {
    // One place to change, and no page can ship an unversioned artefact.
    const fn = SRC.slice(SRC.indexOf("export async function downloadJSON"));
    expect(fn).toMatch(/schema_version: EXPORT_SCHEMA_VERSION/);
  });

  it("puts the version FIRST so a truncated read still finds it", () => {
    // `{ schema_version, ...data }` and not `{ ...data, schema_version }`:
    // the spread must not be able to overwrite the stamp either.
    expect(SRC).toMatch(/schema_version: EXPORT_SCHEMA_VERSION,\s*\.\.\.\(data as object\)/);
  });

  it("leaves arrays and primitives untouched", () => {
    // Wrapping them would change the shape every existing consumer reads,
    // which is a worse problem than the one being solved.
    expect(SRC).toMatch(/!Array\.isArray\(data\)/);
    expect(SRC).toMatch(/typeof data === "object"/);
  });

  it("no page stamps a version of its own", () => {
    // Two sources of the number is how they drift apart.
    const pages = readFileSync(
      join(HERE, "../../pages/QuantumSecureE2E.tsx"), "utf8");
    expect(pages).not.toMatch(/schema_version/);
  });
});
