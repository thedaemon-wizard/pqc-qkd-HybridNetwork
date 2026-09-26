/**
 * The collapsed shell's menu button is a real, labelled disclosure.
 *
 * Below 768px the sidebar is hidden behind a menu button (App.tsx). On a phone
 * that button is the only way to reach the other thirteen pages, so its
 * contract is pinned:
 *
 *   * a <button type="button"> whose accessible name is its visible text,
 *     "Menu" -- not an icon, whose name would depend on a font or a label
 *     someone forgot;
 *   * aria-expanded tracks the state and aria-controls names the panel's id;
 *   * the closed panel is `hidden`, so its links leave the tab order and the
 *     accessibility tree;
 *   * opening moves focus to the first link, Escape closes the menu and puts
 *     focus back on the button, and navigating or pressing outside closes it;
 *   * focus never falls to <body> or stays on a hidden element: closing the
 *     menu over a followed link moves it to <main>, and crossing the
 *     breakpoint with focus in the bar, the panel or the sidebar moves it to
 *     the counterpart in the new layout;
 *   * the panel starts at the bar's bottom edge and ends at the viewport's,
 *     so no strip of page shows under it.
 *
 * The dismissal rules are pure functions (disclosure.ts) and are tested
 * directly; how App.tsx wires them is read from the source, matching the other
 * shell guards, since the tests run in node without a DOM.
 */
import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";

import {
  focusAfterCrossing, focusFallsFromPanel, focusLeftShell, focusWentWithLayout,
  isDismissKey, isOutside, type NodeContainer,
} from "./disclosure";

const APP = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
const APP_CODE = APP.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(?<!:)\/\/[^\n]*/g, "");

describe("isDismissKey", () => {
  it("is Escape", () => {
    expect(isDismissKey("Escape")).toBe(true);
  });

  it("is not the keys that operate the menu", () => {
    for (const key of ["Enter", " ", "Tab", "ArrowDown", "e", ""]) {
      expect(isDismissKey(key)).toBe(false);
    }
  });
});

describe("isOutside", () => {
  const inside = {} as EventTarget;
  const outside = {} as EventTarget;
  const panel: NodeContainer = { contains: (n) => n === (inside as unknown as Node) };

  it("is true for a target the container does not contain", () => {
    expect(isOutside(panel, outside)).toBe(true);
  });

  it("is false for a target inside the container", () => {
    expect(isOutside(panel, inside)).toBe(false);
  });

  it("is false when focus went to nothing, as a click on the panel's plain text does", () => {
    expect(isOutside(panel, null)).toBe(false);
  });

  it("is false when the container is not mounted", () => {
    expect(isOutside(null, outside)).toBe(false);
  });
});

describe("focusFallsFromPanel", () => {
  const link = {} as Element;
  const elsewhere = {} as Element;
  const panel: NodeContainer = { contains: (n) => n === (link as unknown as Node) };

  it("is true when the menu closes while a link in the panel holds focus", () => {
    expect(focusFallsFromPanel(false, panel, link)).toBe(true);
  });

  it("is false while the menu is open", () => {
    expect(focusFallsFromPanel(true, panel, link)).toBe(false);
  });

  it("is false when focus is already outside the panel, as after Escape", () => {
    expect(focusFallsFromPanel(false, panel, elsewhere)).toBe(false);
  });

  it("is false without a panel (the wide layout) or without a focused element", () => {
    expect(focusFallsFromPanel(false, null, link)).toBe(false);
    expect(focusFallsFromPanel(false, panel, null)).toBe(false);
  });
});

describe("focusLeftShell", () => {
  const inside = {} as EventTarget;
  const outside = {} as EventTarget;
  const shell: NodeContainer = { contains: (n) => n === (inside as unknown as Node) };
  const connected = { isConnected: true };
  const unmounted = { isConnected: false };

  it("is false while focus moves within the shell", () => {
    expect(focusLeftShell(shell, connected, inside)).toBe(false);
  });

  it("is true when focus moves out of the shell", () => {
    expect(focusLeftShell(shell, connected, outside)).toBe(true);
  });

  it("is true when focus moves to nothing from a control still on the page", () => {
    // A click on the panel's plain text: the menu stays open (isOutside is
    // false), but no shell control holds focus any more.
    expect(focusLeftShell(shell, connected, null)).toBe(true);
    expect(isOutside(shell, null)).toBe(false);
  });

  it("is false when the control that lost focus was unmounted with its layout", () => {
    expect(focusLeftShell(shell, unmounted, null)).toBe(false);
  });
});

describe("focusWentWithLayout", () => {
  it("is true when the focused shell control was unmounted and focus fell to <body>", () => {
    expect(focusWentWithLayout({ isConnected: false }, true)).toBe(true);
  });

  it("is false when focus was not in the shell, so a crossing takes nothing from the page", () => {
    expect(focusWentWithLayout(null, true)).toBe(false);
  });

  it("is false when the control is still on the page or something else holds focus", () => {
    expect(focusWentWithLayout({ isConnected: true }, true)).toBe(false);
    expect(focusWentWithLayout({ isConnected: false }, false)).toBe(false);
  });
});

describe("focusAfterCrossing", () => {
  const SIDEBAR = ["/", "/e2e", "/console", "/vpn"];

  it("into the collapsed shell is the Menu button, whatever held focus", () => {
    expect(focusAfterCrossing(true, "/console", SIDEBAR)).toBe("menu-button");
    expect(focusAfterCrossing(true, null, SIDEBAR)).toBe("menu-button");
  });

  it("into the sidebar is the link to the same page as the menu link that held focus", () => {
    expect(focusAfterCrossing(false, "/console", SIDEBAR)).toBe(2);
    expect(focusAfterCrossing(false, "/vpn", SIDEBAR)).toBe(3);
  });

  it("into the sidebar is the first link when the Menu button held focus", () => {
    expect(focusAfterCrossing(false, null, SIDEBAR)).toBe(0);
  });

  it("into the sidebar is the first link when no link matches, and -1 without links", () => {
    expect(focusAfterCrossing(false, "/gone", SIDEBAR)).toBe(0);
    expect(focusAfterCrossing(false, "/", [])).toBe(-1);
  });
});

describe("the menu button in App.tsx", () => {
  const start = APP_CODE.indexOf("<button ref={menuButtonRef}");
  const button = APP_CODE.slice(start, APP_CODE.indexOf("</button>", start) + "</button>".length);

  it("is found", () => {
    expect(start, "the menu button moved; these tests are now vacuous").toBeGreaterThan(-1);
  });

  it("is a real button that does not submit anything", () => {
    expect(button).toMatch(/\btype="button"/);
  });

  it("is labelled by its visible text, Menu", () => {
    expect(button).toMatch(/>\s*Menu\s*<\/button>$/);
    // The visible word is the name; an aria-label would let the two drift.
    expect(button).not.toMatch(/aria-label/);
  });

  it("says whether the panel is open and which element the panel is", () => {
    expect(button).toMatch(/aria-expanded=\{menuOpen\}/);
    expect(button).toMatch(/aria-controls=\{NAV_ID\}/);
    expect(APP_CODE).toMatch(/const NAV_ID = "[a-z-]+";/);
  });

  it("controls a panel that is hidden while closed", () => {
    expect(APP_CODE).toMatch(/<aside ref=\{panelRef\} id=\{NAV_ID\} hidden=\{!menuOpen\} style=\{NAV_PANEL\}>/);
    // An inline display would override the hidden attribute and leave the
    // closed links focusable.
    const panel = /const NAV_PANEL: CSSProperties = \{([^;]*)\};/.exec(APP_CODE)?.[1] ?? "";
    expect(panel, "NAV_PANEL is not a style object in App.tsx").not.toBe("");
    expect(panel).not.toMatch(/\bdisplay\s*:/);
  });

  it("the panel holds the same links and attribution as the sidebar", () => {
    // One `navContents`, rendered by the sidebar and by the panel.
    expect(APP_CODE.match(/\{navContents\}/g)).toHaveLength(2);
    expect(APP_CODE.match(/\{ to: "\//g)).toHaveLength(14);
  });

  it("moves focus to the first link when it opens", () => {
    expect(APP_CODE).toMatch(/navRef\.current\?\.querySelector<HTMLElement>\("a\[href\]"\)\?\.focus\(\)/);
  });

  it("closes on Escape and returns focus to the button", () => {
    expect(APP_CODE).toMatch(
      /if \(!isDismissKey\(e\.key\)\) return;\s*setMenuOpen\(false\);\s*menuButtonRef\.current\?\.focus\(\);/);
  });

  it("closes on navigation, and on a press or a focus move outside", () => {
    expect(APP_CODE).toMatch(/useEffect\(\(\) => \{ setMenuOpen\(false\); \}, \[location\.pathname, narrow\]\);/);
    expect(APP_CODE).toMatch(/if \(isOutside\(menuRootRef\.current, e\.target\)\) setMenuOpen\(false\);/);
    expect(APP_CODE).toMatch(/document\.addEventListener\("pointerdown", onPointerDown\)/);
    expect(APP_CODE).toMatch(/isOutside\(e\.currentTarget, e\.relatedTarget\)/);
  });

  it("records which shell control holds focus, in the bar and panel and in the sidebar", () => {
    expect(APP_CODE).toMatch(/const onShellFocus = \(e: FocusEvent<HTMLElement>\) => \{ shellFocusRef\.current = e\.target; \};/);
    expect(APP_CODE).toMatch(
      /if \(focusLeftShell\(e\.currentTarget, e\.target, e\.relatedTarget\)\) shellFocusRef\.current = null;/);
    expect(APP_CODE).toMatch(/if \(isOutside\(e\.currentTarget, e\.relatedTarget\)\) setMenuOpen\(false\);/);
    // Both the top bar (narrow) and the sidebar (wide) report focus.
    expect(APP_CODE.match(/onFocus=\{onShellFocus\} onBlur=\{onShellBlur\}/g)).toHaveLength(2);
  });
});

describe("where focus goes when the menu closes or the layout changes", () => {
  it("<main> can take focus without joining the Tab order", () => {
    expect(APP_CODE).toMatch(/<main ref=\{mainRef\} tabIndex=\{-1\}/);
  });

  it("<main> draws no focus ring, since it is not a control", () => {
    expect(APP_CODE).toMatch(/<main ref=\{mainRef\} tabIndex=\{-1\}\s*style=\{\{[^}]*outline: "none"/);
  });

  it("closing the menu with focus in the panel moves focus to <main>, before the browser drops it", () => {
    expect(APP_CODE).toMatch(/<aside ref=\{panelRef\} id=\{NAV_ID\}/);
    expect(APP_CODE).toMatch(new RegExp(
      String.raw`useLayoutEffect\(\(\) => \{\s*` +
      String.raw`if \(focusFallsFromPanel\(menuOpen, panelRef\.current, document\.activeElement\)\) \{\s*` +
      String.raw`mainRef\.current\?\.focus\(\{ preventScroll: true \}\);\s*\}\s*\}, \[menuOpen\]\);`));
    // Following the current page's link changes no path, so the link's own
    // click handler closes the menu and the effect above moves focus.
    expect(APP_CODE).toMatch(/onClick=\{\(\) => setMenuOpen\(false\)\}/);
  });

  it("crossing the breakpoint moves focus to the counterpart of the unmounted control", () => {
    const effect = /useLayoutEffect\(\(\) => \{\s*const held = shellFocusRef\.current;([\s\S]*?)\}, \[narrow\]\);/
      .exec(APP_CODE)?.[1] ?? "";
    expect(effect, "the crossing effect moved; these checks are now vacuous").not.toBe("");
    expect(effect).toMatch(/if \(!focusWentWithLayout\(held, active === null \|\| active === document\.body\)\) return;/);
    expect(effect).toMatch(/focusAfterCrossing\(narrow, held\.getAttribute\("href"\)/);
    expect(effect).toMatch(/to === "menu-button" \? menuButtonRef\.current : links\[to\]/);
  });
});

describe("the menu panel's geometry", () => {
  /** The body of a `const NAME: CSSProperties = { ... };` style object in App.tsx. */
  const style = (name: string) =>
    new RegExp(`const ${name}: CSSProperties = \\{([^;]*)\\};`).exec(APP_CODE)?.[1] ?? "";

  it("the bar's height is the menu button plus a named padding above and below it", () => {
    expect(APP_CODE).toMatch(/const MENU_BUTTON_MIN_PX = 44;/);
    expect(APP_CODE).toMatch(/const TOP_BAR_PAD_Y_PX = \d+;/);
    expect(APP_CODE).toMatch(/const TOP_BAR_HEIGHT_PX = MENU_BUTTON_MIN_PX \+ 2 \* TOP_BAR_PAD_Y_PX;/);
    const bar = style("TOP_BAR");
    expect(bar, "TOP_BAR is not a style object in App.tsx").not.toBe("");
    expect(bar).toMatch(/height: TOP_BAR_HEIGHT_PX, boxSizing: "border-box"/);
    expect(bar).toMatch(/padding: `\$\{TOP_BAR_PAD_Y_PX\}px \$\{spacing\.lg\}px`/);
  });

  it("the bar has no border, so its border box is its padding box", () => {
    // A border would sit inside TOP_BAR_HEIGHT_PX and shift the panel's
    // offset, which is measured from the padding box, off the bar's edge.
    expect(style("TOP_BAR")).not.toMatch(/\bborder(?:Bottom|Top)?\s*:/);
  });

  it("the panel starts at the bar's bottom edge and ends at the viewport's", () => {
    const panel = style("NAV_PANEL");
    expect(panel).toMatch(/top: TOP_BAR_HEIGHT_PX,/);
    expect(panel).toMatch(/maxHeight: `calc\(100dvh - \$\{TOP_BAR_HEIGHT_PX\}px\)`/);
  });

  it("a scroll that reaches the panel's end does not scroll the page behind it", () => {
    expect(style("NAV_PANEL")).toMatch(/overscrollBehavior: "contain"/);
  });
});
