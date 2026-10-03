/**
 * The dismissal and focus rules of the collapsed shell's menu, kept free of
 * React and of the DOM so they can be tested in the node test environment.
 *
 * The menu is a disclosure: a button with aria-expanded that shows or hides
 * the navigation panel. It is not a modal dialog, so it does not trap focus;
 * instead it closes when focus or a pointer goes somewhere else, because the
 * open panel covers the page and whatever focus reached under it would be
 * invisible. When closing the menu or crossing the breakpoint would drop focus
 * to <body>, the shell moves it to a visible element instead.
 */

/** The key that closes the open menu and returns focus to the menu button. */
export function isDismissKey(key: string): boolean {
  return key === "Escape";
}

/** The part of a DOM node these checks use; a fake satisfies it in tests. */
export interface NodeContainer {
  contains(other: Node | null): boolean;
}

/**
 * Whether `target` is a node outside `container`: a pointer pressed, or focus
 * moved, somewhere other than the menu button and its panel.
 *
 * A null target is not outside. On focusout, a null relatedTarget means focus
 * went to no element at all, which is what a click on the panel's plain text
 * does; closing then would shut the menu under the reader's finger. A missing
 * container (not mounted) has nothing to be outside of.
 */
export function isOutside(container: NodeContainer | null, target: EventTarget | null): boolean {
  if (container === null || target === null) return false;
  return !container.contains(target as Node);
}

/**
 * Whether closing the menu leaves focus inside the panel it is about to hide.
 *
 * Following a link, including the link to the page already shown, or the
 * route changing underneath (the browser's back button) closes the menu while
 * a link in the panel holds focus. A hidden element cannot keep focus, so the
 * browser would drop it to <body> and a keyboard or screen-reader user would
 * start again from the top of the document. The shell moves focus to <main>
 * instead. Escape needs nothing here: it puts focus on the Menu button before
 * the panel hides.
 */
export function focusFallsFromPanel(menuOpen: boolean, panel: NodeContainer | null,
                                    active: Element | null): boolean {
  if (menuOpen || panel === null || active === null) return false;
  return panel.contains(active);
}

/**
 * Whether a focusout means that no shell control (the Menu button, a menu link
 * or a sidebar link) holds focus any more, for the shell's record of which one
 * does.
 *
 * Unlike isOutside, focus moving to nothing counts: after a click on the
 * panel's plain text, or a script's blur(), nothing in the shell holds focus,
 * and a later crossing of the breakpoint must not put focus back on a control
 * the reader had already left. The exception is a control that is no longer in
 * the document: that is the breakpoint unmounting its layout, and the record
 * is what lets the crossing find the control's counterpart.
 */
export function focusLeftShell(container: NodeContainer | null, target: { isConnected: boolean },
                               relatedTarget: EventTarget | null): boolean {
  if (relatedTarget === null) return target.isConnected;
  return isOutside(container, relatedTarget);
}

/**
 * Whether crossing the breakpoint took focus with it: the shell control that
 * held focus (the Menu button, a menu link or a sidebar link) was unmounted
 * with its layout, and focus fell to <body>. `held` is that control, or null
 * when focus was not in the shell, in which case a crossing moves nothing: the
 * shell must not take focus from the page, or put it anywhere when there was
 * none.
 */
export function focusWentWithLayout<T extends { isConnected: boolean }>(
  held: T | null, focusIsLost: boolean,
): held is T {
  return held !== null && !held.isConnected && focusIsLost;
}

/**
 * Where focus goes after crossing the breakpoint took it with the old layout.
 *
 * Into the collapsed shell: the Menu button. The menu is closed after a
 * crossing, so its links are hidden and the button is the one visible control
 * of the navigation.
 *
 * Into the sidebar: the index, in `sidebarHrefs`, of the sidebar link to the
 * page whose menu link held focus, so the reader keeps their place. When the
 * Menu button held it, or no sidebar link matches, the first link. -1 only
 * when the sidebar has no links.
 */
export function focusAfterCrossing(nowNarrow: boolean, heldHref: string | null,
                                   sidebarHrefs: readonly (string | null)[]): "menu-button" | number {
  if (nowNarrow) return "menu-button";
  const same = heldHref === null ? -1 : sidebarHrefs.indexOf(heldHref);
  if (same >= 0) return same;
  return sidebarHrefs.length > 0 ? 0 : -1;
}
