/**
 * The note under `/`'s stack table for an absent profile-gated service must
 * claim only what the row establishes.
 *
 * It said each such service sat behind a profile "which this host's deploy
 * script does not start". That is false for the `ipsec` profile:
 * deploy/deploy.sh starts alice-ipsec and bob-ipsec when given `--ipsec`. What
 * an absent row does establish is that the profile was not started on this
 * host -- so the note says that, with the profile taken from the /api/stack
 * row, and says nothing about which profiles a deploy script can start.
 *
 * These assertions read the source rather than mounting React, matching the
 * other page guards in this directory.
 */
import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = readFileSync(join(HERE, "Overview.tsx"), "utf8");
const DEPLOY = readFileSync(join(HERE, "..", "..", "..", "..", "deploy", "deploy.sh"), "utf8");

/** The rendered paragraph for one absent optional row: its JSX, comments excluded. */
function absentNote(): string {
  const start = SRC.indexOf('stack.filter((s) => s.optional && s.status === "absent").map(');
  expect(start, "the absent-row note moved; this test is now vacuous").toBeGreaterThan(-1);
  const end = SRC.indexOf("</p>", start);
  return SRC.slice(start, end);
}

describe("an absent optional row", () => {
  it("guards the guard: the deploy script really can start the ipsec profile", () => {
    // If this stops holding, the defect this file pins is gone for a different
    // reason, and the assertions below should be reconsidered, not deleted.
    expect(DEPLOY).toMatch(/--ipsec\)[^\n]*--profile ipsec/);
  });

  it("makes no claim about what a deploy script starts", () => {
    expect(absentNote()).not.toMatch(/deploy\s+script/);
  });

  it("says the row's profile was not started on this host", () => {
    const note = absentNote();
    expect(note).toMatch(/\{s\.profile \?\? "\(profile not reported\)"\}/);
    expect(note).toMatch(/profile, which was not\s+started on this host/);
    expect(note).toMatch(/a deployment choice, not a failure/);
  });

  it("the chip's comment no longer says the profile cannot be started", () => {
    expect(SRC).not.toMatch(/deploy script\s*\n?\s*\/\/\s*cannot start/);
  });
});
