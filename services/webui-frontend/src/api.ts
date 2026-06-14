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
export async function postEve(enabled: boolean, prob: number) {
  const r = await fetch(`${BASE}/api/sim/eve`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled, prob }),
  });
  return r.json();
}
export async function postRotate() {
  const r = await fetch(`${BASE}/api/sim/rotate`, { method: "POST" });
  return r.json();
}
export async function postStack(action: "start"|"stop"|"restart", name: string) {
  const r = await fetch(`${BASE}/api/stack/${action}/${name}`, { method: "POST" });
  return r.json();
}

export function openFramesWS(onMsg: (data: any) => void): WebSocket {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${proto}//${location.host}/ws/frames`);
  ws.onmessage = (ev) => {
    try { onMsg(JSON.parse(ev.data)); } catch { /* ignore */ }
  };
  return ws;
}
