/**
 * The one breakpoint of the app shell, and the helpers pages use to follow it.
 *
 * On a 375x812 phone viewport the shell kept its 220px sidebar, which left
 * <main> 155px wide: 13 of 14 routes scrolled sideways (by 48-394px) and /vpn
 * wrapped ten text columns one character per line. At 768px and 1280px no
 * route overflowed (<main> is 548px and 1060px there). So the collapsed shell
 * starts just below 768px, and every page that changes its layout for narrow
 * screens asks this module rather than carrying its own breakpoint: a second
 * breakpoint a few pixels away from this one would give a band of widths where
 * the sidebar is gone but a panel grid is still two columns, or the reverse.
 */
import { useSyncExternalStore } from "react";

/**
 * The widest viewport, in CSS px, that gets the collapsed shell. A 768px
 * tablet keeps the sidebar: measured overflow-free on all 14 routes.
 */
export const NARROW_LAYOUT_MAX_PX = 767;

/** The media query for the collapsed shell, built from NARROW_LAYOUT_MAX_PX. */
export const NARROW_LAYOUT_QUERY = `(max-width: ${NARROW_LAYOUT_MAX_PX}px)`;

/**
 * <main>'s padding in the collapsed shell: a 16px gutter on every side. The
 * wide shell's 2rem side padding would take 64px of a 375px screen.
 */
export const NARROW_MAIN_PADDING = "1rem";

/**
 * A single grid track that may shrink below its content's intrinsic width.
 * A bare `1fr` is `minmax(auto, 1fr)`, and the `auto` minimum is exactly what
 * let a wide <pre> or table widen the whole page (see App.tsx on minWidth: 0).
 */
export const NARROW_COLUMN = "minmax(0, 1fr)";

/**
 * The grid template for a panel grid: one shrinkable column when narrow, and
 * the page's own template, unchanged, otherwise. Pages pass their existing
 * template as `wide`, so the layout at 768px and up is not touched.
 */
export function narrowColumns(narrow: boolean, wide: string): string {
  return narrow ? NARROW_COLUMN : wide;
}

/** The part of a MediaQueryList this module uses; a fake satisfies it in tests. */
export interface NarrowLayoutList {
  matches: boolean;
  addEventListener(type: "change", listener: () => void): void;
  removeEventListener(type: "change", listener: () => void): void;
}

/** The part of `window` this module uses; a fake satisfies it in tests. */
export interface MediaQuerySource {
  matchMedia(query: string): NarrowLayoutList;
}

/** Whether `list` (a list for NARROW_LAYOUT_QUERY) currently matches. */
export function readNarrowLayout(list: NarrowLayoutList): boolean {
  return list.matches;
}

/**
 * Calls `onChange` whenever `list` starts or stops matching, and returns the
 * function that stops listening. It removes the listener from the same list it
 * added it to, so the removal finds it.
 */
export function subscribeNarrowLayout(list: NarrowLayoutList, onChange: () => void): () => void {
  list.addEventListener("change", onChange);
  return () => list.removeEventListener("change", onChange);
}

/**
 * The snapshot and subscribe functions useSyncExternalStore needs, over one
 * MediaQueryList for NARROW_LAYOUT_QUERY that both share.
 *
 * Every Panel and KPI calls useNarrowLayout, and React calls getSnapshot on
 * every render of each of them, and pages that poll live data re-render their
 * panels on every poll. Calling matchMedia there allocated a MediaQueryList
 * per panel per render, and one more per subscription. The list is created on the
 * first call rather than when the module loads, so importing this module
 * where there is no window (the node test environment, a server render) does
 * not touch `window`.
 */
export function createNarrowLayoutStore(source: () => MediaQuerySource) {
  let list: NarrowLayoutList | null = null;
  const shared = (): NarrowLayoutList => (list ??= source().matchMedia(NARROW_LAYOUT_QUERY));
  return {
    getSnapshot: (): boolean => readNarrowLayout(shared()),
    subscribe: (onChange: () => void): (() => void) => subscribeNarrowLayout(shared(), onChange),
  };
}

const store = createNarrowLayoutStore(() => window);
/**
 * Rendering without a window (a server render) has no viewport to measure, so
 * it renders the wide shell, which is what the app rendered before this
 * breakpoint existed. main.tsx uses createRoot, not hydrateRoot, so in the
 * browser the first render already reads the real viewport.
 */
const getServerSnapshot = () => false;

/**
 * True while the viewport is at most NARROW_LAYOUT_MAX_PX wide. Re-renders the
 * caller when the viewport crosses the breakpoint (a rotated phone, a resized
 * window), because the media query's change event drives it.
 */
export function useNarrowLayout(): boolean {
  return useSyncExternalStore(store.subscribe, store.getSnapshot, getServerSnapshot);
}
