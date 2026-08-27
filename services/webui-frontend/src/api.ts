const BASE = "";

export type StackItem = { name: string; status: string; image?: string; started_at?: string };
export type Stats = Record<string, any>;
export type Topo = { nodes: { id: string; label: string; type: string }[]; edges: { source: string; target: string; label: string }[] };

/** Mirrors the `/api/config` response in services/webui-backend/app/main.py. */
export type RuntimeConfig = {
  demo_mode: boolean;
  /** Whether the backend will actually accept /api/stack/* container control.
   *  Reported separately from demo_mode because control is opt-in server-side,
   *  so "not a demo" does not imply "control is available". */
  container_control: boolean;
  rate_limit: { max: number; window_s: number } | null;
};

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
/**
 * Start/stop/restart a container.
 *
 * Throws on a non-2xx. It used to `return r.json()` unconditionally, and that
 * is not a small omission: FastAPI's HTTPException body is valid JSON, so a 403
 * RESOLVED with `{detail: "container control is disabled; ..."}`. The caller
 * discarded the promise, so a refused restart was indistinguishable from a
 * successful one -- no toast, no console entry, not even an unhandled
 * rejection. Measured on the public demo, which renders ten of these buttons
 * while `/api/config` reports `container_control: false`; every click was a
 * silent 403.
 */
export async function postStack(action: "start"|"stop"|"restart", name: string) {
  const r = await fetch(`${BASE}/api/stack/${action}/${name}`, { method: "POST" });
  // `.catch` because an error response is not guaranteed to carry a body --
  // a 502 from a proxy in front of the backend would not.
  const body = await r.json().catch(() => ({} as Record<string, unknown>));
  if (!r.ok) {
    throw new Error(String(body.detail ?? `${action} ${name} failed: HTTP ${r.status}`));
  }
  return body;
}

// Note: BB84 Eve/rotate and the /ws/frames stream were removed in Round 5 — the
// BB84 page now runs its Monte-Carlo client-side (src/lib/sim/bb84Sim.ts).
