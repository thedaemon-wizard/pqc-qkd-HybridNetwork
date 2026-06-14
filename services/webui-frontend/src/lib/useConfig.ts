import { useEffect, useState } from "react";
import { getConfig, type RuntimeConfig } from "../api";

/**
 * Fetches /api/config once (cached process-wide) so pages can adapt the UI for
 * public-demo hardening (DEMO_MODE): hide container-control + server-side export
 * picker. Fails open to demo_mode=false if the backend is unreachable.
 */
let cached: RuntimeConfig | null = null;
let inflight: Promise<RuntimeConfig> | null = null;

export function useRuntimeConfig(): RuntimeConfig {
  const [cfg, setCfg] = useState<RuntimeConfig>(
    cached ?? { demo_mode: false, rate_limit: null });
  useEffect(() => {
    if (cached) { setCfg(cached); return; }
    inflight = inflight ?? getConfig().catch(
      () => ({ demo_mode: false, rate_limit: null } as RuntimeConfig));
    inflight.then((c) => { cached = c; setCfg(c); });
  }, []);
  return cfg;
}

export function useDemoMode(): boolean {
  return useRuntimeConfig().demo_mode;
}
