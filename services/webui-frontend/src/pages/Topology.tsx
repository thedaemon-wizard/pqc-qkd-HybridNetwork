import { useEffect, useRef, useState } from "react";
import { forceCenter, forceLink, forceManyBody, forceSimulation } from "d3-force";
import { getTopology, type Topo } from "../api";
import ExportToolbar from "../components/ExportToolbar";

const WIDTH = 760, HEIGHT = 460;

/**
 * Vertical spacing between the labels of edges that join the same two nodes.
 *
 * alice and bob are joined twice -- wg0, the hop tunnel, and wg1, the data
 * tunnel that runs inside it -- and both edges have the same endpoints, so
 * their lines coincide (which is the truth: wg1 travels inside wg0) and their
 * labels would print on the same spot. One label line of the 10px edge font
 * plus a 2px gap keeps them apart.
 */
const PARALLEL_LABEL_STEP = 12;
/** Radius of a node's circle; its caption sits below it at NODE_CAPTION_DY. */
const NODE_RADIUS = 28;
const NODE_CAPTION_DY = 48;
/**
 * How far above its edge's midpoint an edge label sits: clear of the node
 * circles, plus a small gap. It was 6, which is inside a circle's vertical
 * extent, and once the layout started from an uncrossed square the two
 * horizontal edges were short enough that their labels ran under the circles
 * at both ends. Above the circles a label may be wider than its edge.
 */
const EDGE_LABEL_GAP = 6;
const EDGE_LABEL_LIFT = NODE_RADIUS + EDGE_LABEL_GAP;

/** The force layout's rest length for every link, unchanged. */
const LINK_DISTANCE = 180;

/**
 * Where each node STARTS, before the forces move it: nodes of type "node" on
 * one row, KMEs on the row below, each row in API order, one rest length
 * apart in both directions.
 *
 * d3-force's default start is a phyllotaxis spiral in array order, and for
 * this graph it settled into a crossed square: the alice-bob edge and the
 * kme-a-kme-b edge as the two diagonals, so the two tunnel labels and the
 * "BB84 quantum + classical channel" label all printed on the same midpoint
 * (seen on 2026-09-26, when the second alice-bob label made it worse). Starting
 * from the uncrossed square lets the same forces settle there instead. This
 * reads only `type` and order, so it holds for any graph the API returns; a
 * graph with no such rows falls back to d3's own start.
 */
export function initialPositions(
  nodes: { id: string; type: string }[], width: number, height: number, spacing: number,
): Record<string, { x: number; y: number }> {
  const rows = ["node", "kme"];
  const out: Record<string, { x: number; y: number }> = {};
  rows.forEach((type, r) => {
    const members = nodes.filter((n) => n.type === type);
    members.forEach((n, i) => {
      out[n.id] = {
        x: width / 2 + (i - (members.length - 1) / 2) * spacing,
        y: height / 2 + (r - (rows.length - 1) / 2) * spacing,
      };
    });
  });
  return out;
}

/** For each edge, how many earlier edges join the same unordered pair. */
export function parallelIndex(edges: { source: string; target: string }[]): number[] {
  const seen = new Map<string, number>();
  return edges.map((e) => {
    const key = [e.source, e.target].sort().join(" ");
    const k = seen.get(key) ?? 0;
    seen.set(key, k + 1);
    return k;
  });
}

export default function Topology() {
  const [topo, setTopo] = useState<Topo | null>(null);
  // `null` while the request is in flight, a string once it has failed. Without
  // this the page could only ever say "Loading...", so a backend that is down
  // and a backend that is slow rendered identically -- and forever. Every other
  // backend-dependent page already distinguishes the two: /vpn renders
  // "-- not observed --", /benchmarks and /console catch and report. This was
  // the last page without the path, and it also left the rejection unhandled,
  // so the only trace was a console error nobody sees on a static deploy.
  const [failed, setFailed] = useState<string | null>(null);
  const [positions, setPositions] = useState<Record<string, { x: number; y: number }>>({});
  const simRef = useRef<any>(null);

  useEffect(() => {
    getTopology().then(setTopo).catch((e) => setFailed(String(e?.message ?? e)));
  }, []);

  useEffect(() => {
    if (!topo) return;
    const start = initialPositions(topo.nodes, WIDTH, HEIGHT, LINK_DISTANCE);
    const nodes = topo.nodes.map(n => ({ ...n, ...start[n.id] }));
    // One force link per pair of nodes, however many edges join them. wg0 and
    // wg1 both join alice and bob; simulating both would pull that pair twice
    // as hard as any other and change the layout because a label was added.
    const lane = parallelIndex(topo.edges);
    const links = topo.edges
      .filter((_, i) => lane[i] === 0)
      .map(e => ({ source: e.source, target: e.target, label: e.label }));
    const sim = forceSimulation(nodes as any)
      .force("link", forceLink(links as any).id((d: any) => d.id).distance(LINK_DISTANCE))
      .force("charge", forceManyBody().strength(-500))
      .force("center", forceCenter(WIDTH/2, HEIGHT/2))
      .on("tick", () => {
        const p: Record<string, { x: number; y: number }> = {};
        nodes.forEach((n: any) => { p[n.id] = { x: n.x, y: n.y }; });
        setPositions(p);
      });
    simRef.current = sim;
    // Braces matter: d3's stop() returns the simulation, and a React effect
    // cleanup must return void (a returned value is treated as a destructor).
    return () => { sim.stop(); };
  }, [topo]);

  if (failed) {
    return (
      <div>
        <h2 style={{ marginTop: 0 }}>Network Topology</h2>
        <p style={{ color: "#e0777d" }}>
          Topology not observed — <code>GET /api/topology</code> failed: {failed}
        </p>
        <p style={{ color: "#9aa9d8", fontSize: 13 }}>
          This page reports the running stack, so there is nothing to draw
          client-side. An invented four-node graph would look exactly like a
          measured one, which is the failure this page must not have. See
          <code> docs/deployment-economics.md</code> for which routes survive
          without a backend.
        </p>
      </div>
    );
  }

  if (!topo) return <div>Loading…</div>;

  return (
    <div>
      <h2 style={{ marginTop: 0 }}>Network Topology</h2>
      <p style={{ color: "#9aa9d8" }}>
        Alice and Bob (the WireGuard lane: the wg0 hop tunnel, and the wg1 data
        tunnel inside it, drawn as two edges on one line) and one BB84 + ETSI-014
        KME per side. Four nodes,
        always -- {/* `/api/topology` returns a static list with no multihop branch and no
            signal that would indicate one; its docstring says so, and README was corrected on
            the same grounds. This caption was the last place still promising Charlie. Do not
            redirect the reader to /paper-flow for him: that page draws no Charlie either. */}
        <code>/api/topology</code> has no multi-hop branch, so Charlie is not drawn here or
        anywhere else in the UI. Adding him needs a way to know the profile is active.
      </p>
      <div style={{ marginBottom: 12 }}>
        {/* Not animated: the force layout settles within seconds, so a 10 s
            WebM or GIF of it is a still image. */}
        <ExportToolbar name="topology" pngTargetSelector="#topology-svg" animated={false}
                       jsonProvider={() => ({ topology: topo, layout: positions })} />
      </div>
      <svg id="topology-svg" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} style={{ width: "100%", background: "#0d1320", borderRadius: 8, border: "1px solid #1d2741" }}>
        {(() => {
          const lane = parallelIndex(topo.edges);
          return topo.edges.map((e, i) => {
            const s = positions[e.source], t = positions[e.target];
            if (!s || !t) return null;
            const mx = (s.x + t.x) / 2, my = (s.y + t.y) / 2;
            return (
              <g key={i}>
                <line x1={s.x} y1={s.y} x2={t.x} y2={t.y}
                      stroke="#3a4a78" strokeWidth={1.5} strokeDasharray={e.label.includes("BB84") ? "4 4" : ""} />
                <text x={mx} y={my - EDGE_LABEL_LIFT - lane[i] * PARALLEL_LABEL_STEP}
                      fontSize={10} fill="#7c8cbd" textAnchor="middle">{e.label}</text>
              </g>
            );
          });
        })()}
        {topo.nodes.map((n) => {
          const p = positions[n.id];
          if (!p) return null;
          const fill = n.type === "kme" ? "#7c5cff" : "#3ddc84";
          return (
            <g key={n.id} transform={`translate(${p.x}, ${p.y})`}>
              <circle r={NODE_RADIUS} fill={fill} opacity={0.85} />
              <text textAnchor="middle" dy={4} fontSize={12} fill="#0a0e17" fontWeight={700}>{n.id}</text>
              <text textAnchor="middle" dy={NODE_CAPTION_DY} fontSize={10} fill="#d8e1ff">{n.label}</text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
