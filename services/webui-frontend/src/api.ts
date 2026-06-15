const BASE = "";

export type StackItem = { name: string; status: string; image?: string; started_at?: string };
export type Stats = Record<string, any>;
export type Topo = { nodes: { id: string; label: string; type: string }[]; edges: { source: string; target: string; label: string }[] };

export type RuntimeConfig = { demo_mode: boolean; rate_limit: { max: number; window_s: number } | null };

export async function getConfig(): Promise<RuntimeConfig> {
  const r = await fetch(`${BASE}/api/config`); return r.json();
}

export async function getStack(): Promise<StackItem[]> {
  const r = await fetch(`${BASE}/api/stack`); return r.json();
}
export async function getStats(): Promise<Stats> {
  const r = await fetch(`${BASE}/api/stats`); return r.json();
}
export async function getTopology(): Promise<Topo> {
  const r = await fetch(`${BASE}/api/topology`); return r.json();
}
export async function getLogs(name: string, tail = 200): Promise<{ name: string; log: string }> {
  const r = await fetch(`${BASE}/api/logs/${name}?tail=${tail}`); return r.json();
}
export async function postStack(action: "start"|"stop"|"restart", name: string) {
  const r = await fetch(`${BASE}/api/stack/${action}/${name}`, { method: "POST" });
  return r.json();
}

// Note: BB84 Eve/rotate and the /ws/frames stream were removed in Round 5 — the
// BB84 page now runs its Monte-Carlo client-side (src/lib/sim/bb84Sim.ts).
