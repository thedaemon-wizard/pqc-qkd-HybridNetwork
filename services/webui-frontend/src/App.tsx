import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type FocusEvent } from "react";
import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import ErrorBoundary from "./components/ErrorBoundary";
import { colors, radius, spacing } from "./lib/commonStyles";
import {
  focusAfterCrossing, focusFallsFromPanel, focusLeftShell, focusWentWithLayout, isDismissKey, isOutside,
} from "./lib/disclosure";
import { NARROW_MAIN_PADDING, useNarrowLayout } from "./lib/layout";
import Overview from "./pages/Overview";
import BB84 from "./pages/BB84";
import KeyFlow from "./pages/KeyFlow";
import Topology from "./pages/Topology";
import Benchmarks from "./pages/Benchmarks";
import Console from "./pages/Console";
import PhysicsParams from "./pages/PhysicsParams";
import PQCValidator from "./pages/PQCValidator";
import HIL from "./pages/HIL";
import VpnProtocols from "./pages/VpnProtocols";
import QuantumSecureE2E from "./pages/QuantumSecureE2E";
import PaperDataExchange from "./pages/PaperDataExchange";
import Verification from "./pages/Verification";
import ProtocolLab from "./pages/ProtocolLab";

const nav = [
  { to: "/",            label: "Overview" },
  { to: "/e2e",         label: "Quantum-Secure E2E" },
  { to: "/paper-flow",  label: "Paper Data Exchange" },
  { to: "/bb84",        label: "BB84 Live" },
  { to: "/keyflow",     label: "Key Flow" },
  { to: "/topology",    label: "Topology" },
  { to: "/benchmarks",  label: "Benchmarks" },
  { to: "/console",     label: "Console" },
  { to: "/physics",     label: "Physics Params" },
  { to: "/pqc",         label: "PQC Validator" },
  { to: "/verify",      label: "Verification" },
  { to: "/hil",         label: "Hardware-In-Loop" },
  { to: "/vpn",         label: "VPN Protocols" },
  // Appended last so no existing checklist row that counts sidebar entries
  // is renumbered.
  { to: "/protocol-lab", label: "Protocol Lab" },
];

/** The site name, suffixed to each route's title. */
const SITE_TITLE = "PQC-QKD Hybrid PoC";

/** The id of the navigation panel, which the collapsed shell's menu button controls. */
const NAV_ID = "site-nav";

/** The shell from 768px up: the 220px sidebar, then <main>. */
const WIDE_SHELL: CSSProperties = { display: "grid", gridTemplateColumns: "220px 1fr", minHeight: "100vh" };

/**
 * The shell below 768px (lib/layout.ts, NARROW_LAYOUT_MAX_PX): one column, the
 * top bar above <main>, and no sidebar column.
 *
 * A flex column and not a one-track grid, because the top bar is sticky, and a
 * sticky box cannot leave its containing block. A grid item's containing
 * block is its own grid area, so a bar alone in the first row would scroll
 * away with that row; a flex item's is the whole container, so the bar stays
 * at the top of the viewport for the length of the page.
 */
const NARROW_SHELL: CSSProperties = { display: "flex", flexDirection: "column", minHeight: "100vh" };

/**
 * The menu button's minimum height and width: the 44px target size of WCAG
 * 2.5.5, since on a phone this button is the way to every other page.
 */
const MENU_BUTTON_MIN_PX = 44;

/** The top bar's padding above and below the menu button. */
const TOP_BAR_PAD_Y_PX = 6;

/**
 * The top bar's height, which is its border box: the menu button and the
 * padding above and below it. The menu panel is placed at this offset and
 * sized from it, so the two cannot drift apart when the button changes size.
 */
const TOP_BAR_HEIGHT_PX = MENU_BUTTON_MIN_PX + 2 * TOP_BAR_PAD_Y_PX;

/**
 * The top bar's stacking level, which the open menu panel inherits. Above the
 * saved-exports dropdown (zIndex 50), the one positioned layer the pages set,
 * so the panel covers the page instead of the page's controls showing through.
 */
const TOP_BAR_Z_INDEX = 100;

/**
 * The rule under the top bar is an inset shadow, not a border, so it takes no
 * height: the bar's padding box is its border box, the panel's `top` offset
 * (measured from the padding box) lands exactly on the bar's bottom edge, and
 * the button has the full padding above and below it. With a 1px bottom
 * border the panel started 1px up, over the rule, and ended 1px short of the
 * viewport, showing a strip of page under it (320x568, 2026-09-26).
 */
const TOP_BAR: CSSProperties = {
  position: "sticky", top: 0, zIndex: TOP_BAR_Z_INDEX, flexShrink: 0,
  height: TOP_BAR_HEIGHT_PX, boxSizing: "border-box",
  display: "flex", alignItems: "center", justifyContent: "space-between", gap: spacing.md,
  padding: `${TOP_BAR_PAD_Y_PX}px ${spacing.lg}px`,
  background: colors.panelBg, boxShadow: `inset 0 -1px 0 ${colors.border}`,
};

/**
 * The open menu: a panel under the top bar, the full width of the viewport and
 * over the page. left: 0 and right: 0 size it from the bar, which is exactly
 * the viewport's width, so opening it cannot make the page scroll sideways. It
 * starts at the bar's bottom edge and its height stops at the bottom of the
 * viewport, both from TOP_BAR_HEIGHT_PX, and it scrolls itself; the sidebar's
 * contents are taller than a landscape phone. overscrollBehavior: contain
 * keeps a scroll that reaches the panel's end from scrolling the page behind.
 */
const NAV_PANEL: CSSProperties = {
  position: "absolute", top: TOP_BAR_HEIGHT_PX, left: 0, right: 0,
  maxHeight: `calc(100dvh - ${TOP_BAR_HEIGHT_PX}px)`,
  overflowY: "auto", overscrollBehavior: "contain", boxSizing: "border-box",
  padding: `${spacing.lg}px`,
  background: colors.panelBg, borderBottom: `1px solid ${colors.border}`,
  boxShadow: "0 8px 24px rgba(0,0,0,0.5)",
};

export default function App() {
  const location = useLocation();
  // One title per route. index.html carried "PQC-QKD Hybrid PoC — Console" on
  // every page, naming one route's page for all fourteen.
  useEffect(() => {
    const page = nav.find((n) => n.to === location.pathname)?.label;
    document.title = page ? `${page} — ${SITE_TITLE}` : SITE_TITLE;
  }, [location.pathname]);

  // Below 768px the sidebar is a menu behind a button in a top bar. The
  // 220px column left <main> 155px of a 375px phone, and 13 of 14 routes
  // scrolled sideways. From 768px up the shell is the sidebar grid, unchanged.
  const narrow = useNarrowLayout();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRootRef = useRef<HTMLDivElement>(null);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLElement>(null);
  const navRef = useRef<HTMLElement>(null);
  const mainRef = useRef<HTMLElement>(null);
  // The Menu button, menu link or sidebar link that holds focus, or null once
  // focus leaves the bar, the panel or the sidebar.
  const shellFocusRef = useRef<Element | null>(null);

  // Navigating closes the menu: the reader chose a page and should see it,
  // not the panel over it. So does crossing the breakpoint, so a menu left
  // open at a narrow width is not found open when the window narrows again.
  useEffect(() => { setMenuOpen(false); }, [location.pathname, narrow]);

  // While the menu is open: focus moves into it, to the first link; Escape
  // closes it and returns focus to the button; a pointer pressed outside the
  // bar and panel closes it. pointerdown rather than click, because the click
  // that opened the menu is still being dispatched when this effect adds its
  // listeners, and a document click listener added then would receive that
  // same click and close the menu at once.
  useEffect(() => {
    if (!menuOpen) return;
    navRef.current?.querySelector<HTMLElement>("a[href]")?.focus();
    const onKeyDown = (e: KeyboardEvent) => {
      if (!isDismissKey(e.key)) return;
      setMenuOpen(false);
      menuButtonRef.current?.focus();
    };
    const onPointerDown = (e: PointerEvent) => {
      if (isOutside(menuRootRef.current, e.target)) setMenuOpen(false);
    };
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("pointerdown", onPointerDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("pointerdown", onPointerDown);
    };
  }, [menuOpen]);

  // The panel is about to hide with focus still in it (a link was followed,
  // or the route changed under it): focus goes to <main>, the page the reader
  // chose, instead of dropping to <body>. A layout effect, so it runs in the
  // same task as the commit that hides the panel.
  useLayoutEffect(() => {
    if (focusFallsFromPanel(menuOpen, panelRef.current, document.activeElement)) {
      mainRef.current?.focus({ preventScroll: true });
    }
  }, [menuOpen]);

  // Crossing the breakpoint unmounts the top bar or the sidebar. If that took
  // the focused control with it, focus goes to its counterpart in the new
  // layout: the Menu button, or the sidebar's link to the same page (the first
  // link when the Menu button held it).
  useLayoutEffect(() => {
    const held = shellFocusRef.current;
    const active = document.activeElement;
    if (!focusWentWithLayout(held, active === null || active === document.body)) return;
    shellFocusRef.current = null;
    const links = [...(navRef.current?.querySelectorAll<HTMLElement>("a[href]") ?? [])];
    const to = focusAfterCrossing(narrow, held.getAttribute("href"), links.map((a) => a.getAttribute("href")));
    (to === "menu-button" ? menuButtonRef.current : links[to])?.focus();
  }, [narrow]);

  // Focus leaving the bar and panel closes the menu: the open panel covers
  // the page, so focus that reached under it would be invisible. Focus going
  // to nothing (a click on the panel's plain text) does not close it.
  const onShellFocus = (e: FocusEvent<HTMLElement>) => { shellFocusRef.current = e.target; };
  const onShellBlur = (e: FocusEvent<HTMLElement>) => {
    if (focusLeftShell(e.currentTarget, e.target, e.relatedTarget)) shellFocusRef.current = null;
    if (isOutside(e.currentTarget, e.relatedTarget)) setMenuOpen(false);
  };

  // The links and the algorithm attribution: the sidebar from 768px up, the
  // menu panel below. One layout renders them, never both.
  const navContents = (
    <>
      <nav ref={navRef} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {nav.map(n => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.to === "/"}
            // Also closes the menu when the link is the page already shown,
            // which changes no path for the effect above to see.
            onClick={() => setMenuOpen(false)}
            style={({ isActive }) => ({
              padding: "8px 12px",
              borderRadius: 6,
              textDecoration: "none",
              color: isActive ? "#fff" : "#9aa9d8",
              background: isActive ? "#1a2440" : "transparent",
            })}
          >
            {n.label}
          </NavLink>
        ))}
      </nav>
      {/* Each algorithm is attributed to the lane that uses it. This block
          used to read "ML-KEM-768 + HKDF-SHA3-256" directly above
          "arnika · liboqs · rosenpass", and read top-to-bottom that says
          Rosenpass does ML-KEM. It does not -- the pinned Rosenpass is
          Classic McEliece 460896 + Kyber512. ML-KEM-768 is genuine here, but
          it is the IKEv2 key exchange (RFC 9370), not the PQC half of the
          KDF.

          Release 0.2.0 changed who does what. The PQC half of arnika's HKDF
          is now PQC-HPKE: HPKE Base mode (RFC 9180) with the hybrid KEM
          MLKEM1024-P384, which arnika agrees with its peer itself. Rosenpass
          no longer feeds the HKDF at all; it keys wg1, the WireGuard data
          tunnel that runs inside the wg0 hop tunnel. So each line below
          names its owner: the HKDF, PQC-HPKE, IKEv2, or wg1.

          The IKEv2 line sits between the PQC-HPKE line and the Rosenpass
          line on purpose. The KEM-name guard
          (tests/test_rosenpass_kem_names_match_the_submodule.py) scans
          across line breaks for Rosenpass within 70 characters of an
          ML-KEM name, and this order keeps ML-KEM-1024 out of the
          Rosenpass line's reach while the ML-KEM-768 next to it carries its
          IKEv2 owner.

          Widths measured in the browser against the 187px content box
          before committing (2026-09-26, 11px, the fallback sans-serif of a
          Linux host). The longest line, the HKDF one, renders at 170px. Its
          first form, "HKDF-SHA3-256 (QKD ‖ PQC-HPKE)", measured 185px, 2px
          short of wrapping, and "wg1: Rosenpass (McEliece + Kyber512)"
          measured 195px and did wrap; hence the shorter HKDF line and the
          Rosenpass entry on two lines. The collapsed shell's menu panel is
          wider than the sidebar (the viewport less 16px of padding each
          side), so no line wraps there either. */}
      <div style={{ marginTop: 36, fontSize: 11, color: "#6b7796", lineHeight: 1.5 }}>
        ETSI GS QKD 014<br />
        HKDF-SHA3-256: QKD, PQC-HPKE<br />
        PQC-HPKE: ML-KEM-1024 + P-384<br />
        IKEv2: ML-KEM-768 (RFC 9370)<br />
        wg1 PSK: Rosenpass<br />
        Rosenpass: McEliece + Kyber512<br />
        arnika · liboqs · rosenpass
      </div>
    </>
  );

  return (
    <div style={narrow ? NARROW_SHELL : WIDE_SHELL}>
      {/* Both layouts put <main> second, so crossing the breakpoint (turning a
          phone sideways) replaces the sidebar or the top bar and keeps the
          page mounted, with whatever state it holds. */}
      {narrow ? (
        <div ref={menuRootRef} style={TOP_BAR} onFocus={onShellFocus} onBlur={onShellBlur}>
          <h1 style={{ fontSize: 16, margin: 0, lineHeight: 1.3, minWidth: 0 }}>{SITE_TITLE}</h1>
          {/* A real button with a visible word, not an icon: its accessible
              name is its text. aria-expanded says whether the panel is open,
              and aria-controls names the panel. */}
          <button ref={menuButtonRef} type="button"
                  aria-expanded={menuOpen} aria-controls={NAV_ID}
                  onClick={() => setMenuOpen((open) => !open)}
                  style={{
                    minHeight: MENU_BUTTON_MIN_PX, minWidth: MENU_BUTTON_MIN_PX,
                    padding: `0 ${spacing.lg}px`, flexShrink: 0,
                    background: menuOpen ? colors.active : "transparent",
                    color: colors.textPri, border: `1px solid ${colors.borderLt}`,
                    borderRadius: radius.md, fontSize: 14, fontWeight: 600, cursor: "pointer",
                  }}>
            Menu
          </button>
          {/* `hidden`, not an off-screen position or zero opacity, so the
              closed panel's links leave the tab order and the accessibility
              tree. The panel's style sets no display, which would override
              the attribute. */}
          <aside ref={panelRef} id={NAV_ID} hidden={!menuOpen} style={NAV_PANEL}>
            {navContents}
          </aside>
        </div>
      ) : (
        <aside id={NAV_ID} onFocus={onShellFocus} onBlur={onShellBlur}
               style={{ background: "#0d1320", padding: "1.5rem 1rem", borderRight: "1px solid #1d2741" }}>
          <h1 style={{ fontSize: 18, marginTop: 0, marginBottom: 24, lineHeight: 1.3 }}>
            PQC-QKD<br />Hybrid PoC
          </h1>
          {navContents}
        </aside>
      )}
      {/* minWidth: 0 is load bearing, not cosmetic.
        *
        * A grid item's min-width defaults to `auto`, which means "do not
        * shrink below the intrinsic width of my content". The `1fr` track
        * therefore grew to fit the widest thing inside it, and on /console
        * that is a <pre> of container logs whose lines run past 1400px. The
        * <pre> sets overflow-x: auto and could have scrolled internally, but
        * it was never asked to: the track had already widened to accommodate
        * it, so the WHOLE PAGE scrolled sideways instead.
        *
        * Measured on the deployed build at a 1280px viewport: body.scrollWidth
        * 1713 against innerWidth 1280 -- 433px of horizontal scroll, on every
        * page, because <main> is shared. /console was simply the page with
        * content wide enough to trigger it.
        *
        * With minWidth: 0 the track may shrink and the <pre> scrolls itself,
        * which is what its overflow-x was for.
        *
        * Below 768px <main> is a flex item of a column instead, stretched to
        * the viewport's width, and its padding is the narrower
        * NARROW_MAIN_PADDING. It keeps minWidth: 0 there too: harmless in a
        * column, and the same shell either side of the breakpoint.
        *
        * tabIndex={-1} lets the shell move focus here when the menu closes
        * over a followed link (see focusFallsFromPanel), without adding
        * <main> to the Tab order. outline: none because <main> is not a
        * control: without it, once <main> held focus after a keyboard step
        * (following a menu link with Enter, or at any width a click on the
        * page's text followed by an arrow key), the browser drew its focus
        * ring around the whole page (measured 2026-09-26). The outline takes
        * no space, so the layout at every width is unchanged. */}
      <main ref={mainRef} tabIndex={-1}
            style={{ padding: narrow ? NARROW_MAIN_PADDING : "1.5rem 2rem", minWidth: 0, outline: "none" }}>
        <ErrorBoundary key={location.pathname}>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/bb84" element={<BB84 />} />
          <Route path="/keyflow" element={<KeyFlow />} />
          <Route path="/topology" element={<Topology />} />
          <Route path="/benchmarks" element={<Benchmarks />} />
          <Route path="/console" element={<Console />} />
          <Route path="/physics" element={<PhysicsParams />} />
          <Route path="/pqc" element={<PQCValidator />} />
          <Route path="/verify" element={<Verification />} />
          <Route path="/hil" element={<HIL />} />
          <Route path="/vpn" element={<VpnProtocols />} />
          <Route path="/e2e" element={<QuantumSecureE2E />} />
          <Route path="/paper-flow" element={<PaperDataExchange />} />
          <Route path="/protocol-lab" element={<ProtocolLab />} />
        </Routes>
        </ErrorBoundary>
      </main>
    </div>
  );
}
