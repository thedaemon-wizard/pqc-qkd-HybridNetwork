import { useEffect, useState } from "react";
import { getConfig, type RuntimeConfig } from "../api";

/**
 * Fetches /api/config once (cached process-wide) so pages can adapt the UI to
 * the deployment's posture.
 *
 * Fails CLOSED. The previous default assumed `demo_mode: false` whenever the
 * backend could not be reached, which showed container-control buttons on a
 * deployment whose posture was unknown. Assuming the most restrictive posture
 * until the backend says otherwise costs nothing -- a hidden button on a
 * trusted host is a small annoyance, a visible one on an exposed host is not.
 */
const RESTRICTIVE: RuntimeConfig = {
  demo_mode: true,
  container_control: false,
  rate_limit: null,
};

let cached: RuntimeConfig | null = null;
let inflight: Promise<RuntimeConfig> | null = null;

export function useRuntimeConfig(): RuntimeConfig {
  const [cfg, setCfg] = useState<RuntimeConfig>(cached ?? RESTRICTIVE);
  useEffect(() => {
    if (cached) { setCfg(cached); return; }
    inflight = inflight ?? getConfig().catch(() => RESTRICTIVE);
    inflight.then((c) => { cached = c; setCfg(c); });
  }, []);
  return cfg;
}

export function useDemoMode(): boolean {
  return useRuntimeConfig().demo_mode;
}

/**
 * Whether the backend will actually accept a container-control request.
 *
 * Gate the UI on this rather than on `!demo_mode`: container control is opt-in
 * server-side, so "not a demo" no longer implies "control is available".
 */
export function useContainerControl(): boolean {
  return useRuntimeConfig().container_control === true;
}
