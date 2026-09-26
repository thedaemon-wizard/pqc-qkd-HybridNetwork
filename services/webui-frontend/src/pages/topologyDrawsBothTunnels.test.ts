/**
 * /topology draws both alice-bob tunnels without printing one label on another.
 *
 * Since release 0.2.0 `/api/topology` returns two alice-bob edges: wg0, the hop
 * tunnel, and wg1, the data tunnel inside it. The page drew every edge label at
 * its edge's midpoint, so the second label landed exactly on the first. It also
 * settled, from d3-force's default start, into a crossed square whose two
 * diagonals were the tunnel edge and the BB84 channel edge, so all three labels
 * shared one midpoint. Measured in the browser on 2026-09-26 at 1280px: after
 * the fixes pinned here, no label overlaps another label or a node circle.
 */
import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { initialPositions, parallelIndex } from "./Topology";

const HERE = new URL(".", import.meta.url).pathname;
const SRC = readFileSync(join(HERE, "Topology.tsx"), "utf8");

/** The shape `/api/topology` returns, ids and types only. */
const NODES = [
  { id: "alice", type: "node" }, { id: "bob", type: "node" },
  { id: "kme-a", type: "kme" }, { id: "kme-b", type: "kme" },
];
const EDGES = [
  { source: "alice", target: "bob" },
  { source: "alice", target: "bob" },
  { source: "alice", target: "kme-a" },
  { source: "bob", target: "kme-b" },
  { source: "kme-a", target: "kme-b" },
];

describe("parallel edges", () => {
  it("are numbered per unordered pair, in order", () => {
    expect(parallelIndex(EDGES)).toEqual([0, 1, 0, 0, 0]);
    expect(parallelIndex([{ source: "a", target: "b" }, { source: "b", target: "a" }]))
      .toEqual([0, 1]);
  });

  it("lift each later label one step above the one before", () => {
    expect(SRC).toMatch(/y=\{my - EDGE_LABEL_LIFT - lane\[i\] \* PARALLEL_LABEL_STEP\}/);
  });

  it("are simulated once, so a second label does not change the layout", () => {
    expect(SRC).toMatch(/\.filter\(\(_, i\) => lane\[i\] === 0\)/);
  });
});

describe("the layout starts uncrossed", () => {
  const p = initialPositions(NODES, 760, 460, 180);

  it("puts the nodes on one row and the KMEs on the row below", () => {
    expect(p.alice.y).toBe(p.bob.y);
    expect(p["kme-a"].y).toBe(p["kme-b"].y);
    expect(p["kme-a"].y).toBeGreaterThan(p.alice.y);
  });

  it("keeps each KME under its own node, in API order", () => {
    expect(p.alice.x).toBeLessThan(p.bob.x);
    expect(p["kme-a"].x).toBe(p.alice.x);
    expect(p["kme-b"].x).toBe(p.bob.x);
  });

  it("leaves a node of another type to d3's own start", () => {
    expect(initialPositions([{ id: "x", type: "other" }], 760, 460, 180)).toEqual({});
  });
});

describe("edge labels clear the node circles", () => {
  it("sit above a circle's radius, not inside it", () => {
    expect(SRC).toMatch(/const EDGE_LABEL_LIFT = NODE_RADIUS \+ EDGE_LABEL_GAP;/);
    expect(SRC).toMatch(/<circle r=\{NODE_RADIUS\}/);
  });
});
