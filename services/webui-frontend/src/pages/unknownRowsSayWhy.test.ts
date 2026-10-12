/**
 * An `unknown` row on / says why nobody could look.
 *
 * Since the backend gave up the Docker socket, every container status comes
 * from stack-status. Where none runs -- the sim-only demo overlay -- every row
 * of /api/stack is `unknown` with the same `error`, "container status is not
 * available on this deployment: ...", and where Docker failed for one
 * container that row carries Docker's reason. The page rendered all of them as
 * grey `unknown` chips and nothing else, so "this host runs no stack-status"
 * and "the daemon is restarting" looked the same.
 */
import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import { join } from "node:path";

import type { StackItem } from "../api";
import { unknownReasons } from "./Overview";

const HERE = new URL(".", import.meta.url).pathname;
const SRC = readFileSync(join(HERE, "Overview.tsx"), "utf8");

const NOT_HERE = "container status is not available on this deployment: STACK_STATUS_URL is not set";

describe("unknownReasons", () => {
  it("gives a reason once, with every row it applies to", () => {
    const stack: StackItem[] = ["alice", "bob", "stack-status"].map((name) => (
      { name, status: "unknown", error: NOT_HERE }));
    expect(unknownReasons(stack)).toEqual([{ names: ["alice", "bob", "stack-status"], why: NOT_HERE }]);
  });

  it("keeps different reasons apart", () => {
    const stack: StackItem[] = [
      { name: "alice", status: "running" },
      { name: "bob", status: "unknown", error: "500 Server Error: daemon restarting" },
      { name: "qkdnetsim-kme", status: "absent", optional: true },
      { name: "bb84-kme-a", status: "unknown", error: "read timed out" },
    ];
    expect(unknownReasons(stack)).toEqual([
      { names: ["bob"], why: "500 Server Error: daemon restarting" },
      { names: ["bb84-kme-a"], why: "read timed out" },
    ]);
  });

  it("says nothing for a row that gave no reason, or is not unknown", () => {
    expect(unknownReasons([{ name: "alice", status: "unknown" },
                           { name: "bob", status: "exited", error: "x" }])).toEqual([]);
  });
});

describe("the page", () => {
  it("prints each reason under the table, as text", () => {
    expect(SRC).toMatch(/\{unknownReasons\(stack\)\.map\(\(\{ names, why \}\) => \(/);
    expect(SRC).toMatch(/Not observed\{names\.length === stack\.length \? "" : ` \(\$\{names\.join\(", "\)\}\)`\}: \{why\}\./);
  });

  it("and on the chip, as its title", () => {
    expect(SRC).toMatch(/if \(s\.status === "unknown" && s\.error\) \{\s*return \{ label: s\.status, color: STATUS_COLOR\.unknown, title: s\.error \};/);
  });
});
