/**
 * The poller loads once on mount even in a hidden tab, and only the REPEATING
 * ticks wait for the tab to be visible.
 *
 * The first call used to be skipped too, so /physics opened in a background
 * tab said "Loading parameters..." until someone brought it to the front.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { startPoll, type VisibilitySource } from "./usePoll";

function fakeDoc(state: DocumentVisibilityState) {
  const listeners = new Set<() => void>();
  const doc: VisibilitySource & { set(s: DocumentVisibilityState): void; count(): number } = {
    visibilityState: state,
    addEventListener: (_t, cb) => { listeners.add(cb); },
    removeEventListener: (_t, cb) => { listeners.delete(cb); },
    set(s) { this.visibilityState = s; listeners.forEach((cb) => cb()); },
    count: () => listeners.size,
  };
  return doc;
}

afterEach(() => { vi.useRealTimers(); });

describe("startPoll", () => {
  it("loads once immediately in a hidden tab", () => {
    vi.useFakeTimers();
    const fn = vi.fn();
    const stop = startPoll(fn, 1000, fakeDoc("hidden"));
    expect(fn).toHaveBeenCalledTimes(1);
    stop();
  });

  it("skips the repeating ticks while hidden and catches up when shown", () => {
    vi.useFakeTimers();
    const fn = vi.fn();
    const doc = fakeDoc("hidden");
    const stop = startPoll(fn, 1000, doc);
    vi.advanceTimersByTime(5000);
    expect(fn).toHaveBeenCalledTimes(1);
    doc.set("visible");
    expect(fn).toHaveBeenCalledTimes(2);
    vi.advanceTimersByTime(3000);
    expect(fn).toHaveBeenCalledTimes(5);
    stop();
  });

  it("polls on the interval while visible, and stop() ends everything", () => {
    vi.useFakeTimers();
    const fn = vi.fn();
    const doc = fakeDoc("visible");
    const stop = startPoll(fn, 500, doc);
    vi.advanceTimersByTime(1000);
    expect(fn).toHaveBeenCalledTimes(3);
    stop();
    expect(doc.count()).toBe(0);
    vi.advanceTimersByTime(5000);
    doc.set("visible");
    expect(fn).toHaveBeenCalledTimes(3);
  });
});
