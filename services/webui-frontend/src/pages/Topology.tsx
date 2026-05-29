import { useEffect, useRef, useState } from "react";
import { forceCenter, forceLink, forceManyBody, forceSimulation } from "d3-force";
import { getTopology, type Topo } from "../api";

const WIDTH = 760, HEIGHT = 460;

export default function Topology() {
  const [topo, setTopo] = useState<Topo | null>(null);
  const [positions, setPositions] = useState<Record<string, { x: number; y: number }>>({});
  const simRef = useRef<any>(null);

  useEffect(() => { getTopology().then(setTopo); }, []);

  useEffect(() => {
    if (!topo) return;
    const nodes = topo.nodes.map(n => ({ ...n }));
    const links = topo.edges.map(e => ({ source: e.source, target: e.target, label: e.label }));
    const sim = forceSimulation(nodes as any)
      .force("link", forceLink(links as any).id((d: any) => d.id).distance(180))
      .force("charge", forceManyBody().strength(-500))
      .force("center", forceCenter(WIDTH/2, HEIGHT/2))
      .on("tick", () => {
        const p: Record<string, { x: number; y: number }> = {};
        nodes.forEach((n: any) => { p[n.id] = { x: n.x, y: n.y }; });
        setPositions(p);
      });
    simRef.current = sim;
    return () => sim.stop();
  }, [topo]);

  if (!topo) return <div>Loading…</div>;

  return (
    <div>
      <h2 style={{ marginTop: 0 }}>Network Topology</h2>
      <p style={{ color: "#9aa9d8" }}>
        Alice / Bob (WireGuard hop), 各 KME (BB84 + ETSI-014), マルチホップ時は Charlie が中継。
      </p>
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} style={{ width: "100%", background: "#0d1320", borderRadius: 8, border: "1px solid #1d2741" }}>
        {topo.edges.map((e, i) => {
          const s = positions[e.source], t = positions[e.target];
          if (!s || !t) return null;
          const mx = (s.x + t.x) / 2, my = (s.y + t.y) / 2;
          return (
            <g key={i}>
              <line x1={s.x} y1={s.y} x2={t.x} y2={t.y}
                    stroke="#3a4a78" strokeWidth={1.5} strokeDasharray={e.label.includes("BB84") ? "4 4" : ""} />
              <text x={mx} y={my - 6} fontSize={10} fill="#7c8cbd" textAnchor="middle">{e.label}</text>
            </g>
          );
        })}
        {topo.nodes.map((n) => {
          const p = positions[n.id];
          if (!p) return null;
          const fill = n.type === "kme" ? "#7c5cff" : "#3ddc84";
          return (
            <g key={n.id} transform={`translate(${p.x}, ${p.y})`}>
              <circle r={28} fill={fill} opacity={0.85} />
              <text textAnchor="middle" dy={4} fontSize={12} fill="#0a0e17" fontWeight={700}>{n.id}</text>
              <text textAnchor="middle" dy={48} fontSize={10} fill="#d8e1ff">{n.label}</text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
