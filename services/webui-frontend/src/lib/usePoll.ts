import { useEffect, useRef } from "react";

/**
 * Call `fn` now and every `ms`, but not while the tab is hidden.
 *
 * Every live-state page polled with a bare setInterval, so a tab left in the
 * background kept asking the public demo for container logs and stack status
 * nobody was looking at. Chrome throttles hidden timers to about once a second,
 * which slows this down but does not stop it. A hidden tab now skips its ticks
 * and polls once as soon as it becomes visible again.
 */
export function usePoll(fn: () => unknown, ms: number): void {
  const latest = useRef(fn);
  latest.current = fn;
  useEffect(() => {
    const tick = () => {
      if (typeof document !== "undefined" && document.visibilityState === "hidden") return;
      void latest.current();
    };
    tick();
    const t = setInterval(tick, ms);
    const onVisible = () => { if (document.visibilityState === "visible") tick(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => { clearInterval(t); document.removeEventListener("visibilitychange", onVisible); };
  }, [ms]);
}
