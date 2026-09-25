import { useEffect, useRef } from "react";

/** The slice of `document` the poller reads, so the logic runs without a DOM. */
export interface VisibilitySource {
  visibilityState: DocumentVisibilityState;
  addEventListener(type: "visibilitychange", cb: () => void): void;
  removeEventListener(type: "visibilitychange", cb: () => void): void;
}

/**
 * Call `fn` once now, then every `ms` while the page is visible, and once
 * more whenever it becomes visible again. Returns the stop function.
 *
 * The FIRST call is unconditional. It used to be skipped for a hidden tab
 * like every later tick, so a page opened in a background tab -- a
 * middle-click, or a verification script driving a tab that is not in front
 * -- rendered "Loading parameters..." until someone looked at it; on
 * 2026-09-25 /physics sat on that line for minutes in exactly that case.
 * Loading once costs one request; skipping it costs a page that says nothing.
 */
export function startPoll(fn: () => unknown, ms: number, doc: VisibilitySource): () => void {
  const tick = () => { if (doc.visibilityState !== "hidden") void fn(); };
  void fn();
  const t = setInterval(tick, ms);
  const onVisible = () => { if (doc.visibilityState === "visible") void fn(); };
  doc.addEventListener("visibilitychange", onVisible);
  return () => { clearInterval(t); doc.removeEventListener("visibilitychange", onVisible); };
}

/**
 * Every live-state page polled with a bare setInterval, so a tab left in the
 * background kept asking the public demo for container logs and stack status
 * nobody was looking at. Chrome throttles hidden timers to about once a second,
 * which slows this down but does not stop it. A hidden tab now skips its ticks
 * and polls once as soon as it becomes visible again.
 */
export function usePoll(fn: () => unknown, ms: number): void {
  const latest = useRef(fn);
  latest.current = fn;
  useEffect(() => startPoll(() => latest.current(), ms, document), [ms]);
}
