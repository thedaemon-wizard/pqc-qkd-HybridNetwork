import { useEffect, useLayoutEffect, useState, type CSSProperties, type ReactNode } from "react";

/**
 * The box's contract: maxWidth: 100% keeps it inside its column, and
 * overflowX: auto scrolls whatever is wider (a table, a chart) inside the box
 * instead of letting it widen the page. A grid track of minmax(0, 1fr) does
 * not do this on its own: the content still overflows the track.
 */
export const SCROLL_REGION_STYLE: CSSProperties = { overflowX: "auto", maxWidth: "100%" };

/**
 * How many CSS px scrollWidth may exceed clientWidth while the box still
 * counts as not scrolling. Both are whole pixels: measured in Chrome 152 on
 * 2026-09-26, content 0.2px wider than its box read one pixel wider, and an
 * exact fit read equal. A fraction of a pixel out of view hides nothing, and
 * a Tab stop for it would be one that does nothing.
 */
export const SUBPIXEL_OVERFLOW_PX = 1;

/**
 * Whether a box with this scrollWidth and clientWidth scrolls sideways: its
 * content is wider than the box by more than SUBPIXEL_OVERFLOW_PX.
 */
export function scrollsSideways(scrollWidth: number, clientWidth: number): boolean {
  return scrollWidth - clientWidth > SUBPIXEL_OVERFLOW_PX;
}

/** The attributes that make a scrolling box a named region the keyboard can reach. */
export interface ScrollRegionAttributes {
  role?: "region";
  tabIndex?: 0;
  "aria-label"?: string;
  "aria-describedby"?: string;
}

/**
 * The box's attributes: role="region", tabIndex 0 and the label (and the
 * description, if one is given) while it scrolls sideways, and none at all
 * while it does not.
 *
 * A box that scrolls must be reachable by keyboard, or a reader without a
 * pointer cannot scroll it: focus on it lets the arrow keys scroll it, and the
 * name says what focus reached. A box that does not scroll gets no Tab stop,
 * because a stop that does nothing is noise, and no aria-label, which is not
 * allowed on a div without a role. None of these attributes takes any space,
 * and neither does the focus ring (an outline), so adding or removing them
 * never changes the widths the decision is made from.
 */
export function scrollRegionAttributes(scrolls: boolean, label: string, describedBy?: string): ScrollRegionAttributes {
  if (!scrolls) return {};
  return describedBy === undefined
    ? { role: "region", tabIndex: 0, "aria-label": label }
    : { role: "region", tabIndex: 0, "aria-label": label, "aria-describedby": describedBy };
}

/** The part of a box watchSideScroll reads; an Element satisfies it. */
export interface SideScrollBox<N> {
  readonly scrollWidth: number;
  readonly clientWidth: number;
  readonly firstElementChild: N | null;
}

/** The observers watchSideScroll uses: the browser's own, or fakes in a test. */
export interface SideScrollObservers<N> {
  resize(onResize: () => void): { observe(node: N): void; unobserve(node: N): void; disconnect(): void };
  childList(onChange: () => void): { observe(node: N, options: MutationObserverInit): void; disconnect(): void };
}

/**
 * Calls `onChange` with whether `box` scrolls sideways: once now, and again
 * each time the answer changes. Returns the function that stops watching.
 *
 * The widths change when the box changes size (the viewport, the layout
 * around it) and when its content does (rows arrive, a table lays out again),
 * so a ResizeObserver watches the box and its content, the first element
 * child. A ResizeObserver cannot see two things, and only the first is
 * watched for:
 *
 *  - The content being replaced. A component inside the box that renders a
 *    different root element would leave the observer on a detached element,
 *    and the answer would never change again. A MutationObserver on the box's
 *    own list of children (not its subtree) fires on exactly that, and moves
 *    the resize watch to the new first element child.
 *  - Something inside the content drawn wider or narrower while the content's
 *    own box keeps its size, as Plotly does on /keyflow: after a resize from
 *    375px to 768px it redraws the chart at 484px only after its div is 484px
 *    already, and a hover label near the chart's right edge runs past that
 *    div. Measured in Chrome 152 on 2026-09-26: with neither watched, the box
 *    stayed a region at 768px after that resize; with the subtree watched, it
 *    became a region and then not one again as the pointer crossed the
 *    chart's right edge, at 1280px and at 768px. So this is not watched, and
 *    what the content draws may change width only together with the
 *    content's own box: a table grows with its rows, the /vpn <pre> holds
 *    fixed text, and /keyflow clips its chart to its own div (KeyFlow.tsx).
 */
export function watchSideScroll<N>(box: SideScrollBox<N> & N, onChange: (scrolls: boolean) => void,
                                   observers: SideScrollObservers<N>): () => void {
  let last: boolean | undefined;
  const measure = () => {
    const now = scrollsSideways(box.scrollWidth, box.clientWidth);
    if (now === last) return;
    last = now;
    onChange(now);
  };
  const sizes = observers.resize(measure);
  let content: N | null = null;
  const followContent = () => {
    const next = box.firstElementChild;
    if (next === content) return;
    if (content !== null) sizes.unobserve(content);
    content = next;
    if (content !== null) sizes.observe(content);
  };
  const children = observers.childList(() => { followContent(); measure(); });
  sizes.observe(box);
  followContent();
  children.observe(box, { childList: true });
  measure();
  return () => { sizes.disconnect(); children.disconnect(); };
}

/** The browser's observers, created only when a box is watched. */
const BROWSER_OBSERVERS: SideScrollObservers<Element> = {
  resize: (onResize) => new ResizeObserver(onResize),
  childList: (onChange) => new MutationObserver(onChange),
};

/**
 * useLayoutEffect in the browser, so the first paint already has the right
 * attributes, and useEffect where there is no window: React 18 warns about
 * useLayoutEffect in a server render, and neither runs there.
 */
const useClientLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;

/**
 * A ref callback for a box, and whether that box scrolls sideways now. Until
 * the box is in the document (and in a server render) the answer is false.
 */
export function useScrollsSideways<T extends HTMLElement>(): [(box: T | null) => void, boolean] {
  const [box, setBox] = useState<T | null>(null);
  const [scrolls, setScrolls] = useState(false);
  useClientLayoutEffect(() => {
    if (box === null) {
      setScrolls(false);
      return undefined;
    }
    return watchSideScroll<Element>(box, setScrolls, BROWSER_OBSERVERS);
  }, [box]);
  return [setBox, scrolls];
}

export interface ScrollRegionProps {
  /**
   * What the box holds, for example "Container status table". Required:
   * while the box scrolls it is a focusable region, and without a name a
   * region is not exposed as one: the reader would be told nothing about
   * what focus reached.
   */
  "aria-label": string;
  /**
   * The id of visible text that says how to use the box, such as a line
   * under it saying that it scrolls. Given to the region with its name, so
   * the label can stay a name and the instruction is not announced twice.
   */
  "aria-describedby"?: string;
  /**
   * Extra style for the box, such as a margin. It cannot replace overflowX or
   * maxWidth, which are the reason the box exists.
   */
  style?: CSSProperties;
  children: ReactNode;
}

/**
 * A box whose content scrolls sideways inside it rather than the page.
 *
 * While the content is wider than the box, at any viewport width, the box is
 * also role="region" with tabIndex 0 and the given aria-label
 * (scrollRegionAttributes); while it fits, it is a plain div. So a box that
 * scrolls can always be reached and scrolled from the keyboard, and one that
 * does not scroll adds no Tab stop. A server render has nothing to measure
 * and renders the plain div.
 */
export default function ScrollRegion({ "aria-label": label, "aria-describedby": describedBy, style, children }: ScrollRegionProps) {
  const [ref, scrolls] = useScrollsSideways<HTMLDivElement>();
  const box: CSSProperties = { ...style, ...SCROLL_REGION_STYLE };
  return (
    <div ref={ref} {...scrollRegionAttributes(scrolls, label, describedBy)} style={box}>
      {children}
    </div>
  );
}
