#!/usr/bin/env python3
"""Walk every tab of the SPA in headless Chrome and use every control on it.

scripts/csp_smoke.py opens each route once; scripts/protocol_lab_smoke.py plays
the Protocol Lab in depth. This is the breadth between them. It reaches each tab
by its link in the site's menu, as a reader does, on the same build and under the
same enforced Content-Security-Policy (deploy/Caddyfile):

  tabs      the menu walked forward, backward, and at speed (each link pressed
            40 ms after the last, before that tab has settled), then every link
            inside a page that leads to another tab. Each arrival must be the
            tab asked for, marked current in the menu, with its own heading
            drawn (VERIFICATION_CHECKLIST row 4.3.8)
  controls  on every tab, each control a reader can use: every button pressed,
            every select set to each of its options, every number and range
            set to its limits, a value between them, a value past each limit
            and nothing at all, every checkbox ticked and cleared. A control
            that is disabled when it is reached is tried again after the others
            -- Pause once Run has been pressed -- and must look disabled while it
            is: an opacity below 1 and the not-allowed cursor (4.3.9)
  leave     each tab, its simulation started where it has a Run button, left for
            /hil, a page that animates and polls nothing: nothing the tab
            started may still run there -- no interval, animation frame, timer
            or open socket beyond /hil's own (4.3.10)
  exports   Logs, JSON, CSV and PNG on every tab that offers them, after three
            Steps where the tab has a Step button: each press must produce one
            file of its kind -- text with a line in it, JSON that parses, CSV
            with a header and a row, a PNG that decodes -- and no
            "export failed" (4.3.11)

Every check fails on the page's error boundary, an uncaught exception, a console
error, a CSP violation, or text a reader should never be shown: NaN, undefined,
Infinity or [object ...], outside a log or a code block. Each run first plants
one of each, a timer left running and a write, and exits 2 unless it sees them
all, so a run that could not see a failure cannot pass.

What it never presses: an export button outside the exports phase, the
recordings (WebM and GIF, rows 4.5.x), the plot library's own download button,
the "shared gallery" checkbox (its label is read from ExportToolbar.tsx), a file
input, or a button whose label restarts, starts, stops, deletes or removes. And
no request other than GET or HEAD leaves the page: the helper answers each one
403 itself, as the hardened demo answers the writes it refuses, and counts it.
So the check never restarts a container, saves to the shared gallery or deletes
from it, on the local build or with --base. An export is read in the page, from
the Blob it made, and never saved.

    npx vite build                      # in services/webui-frontend
    python3 scripts/spa_tabs_smoke.py
    python3 scripts/spa_tabs_smoke.py --base https://<the demo's host>

--base drives the deployed page instead (after a deploy): nothing is served from
here, the policy is whatever the host sends, and the pages read the running stack.

Exit status: 0 every check passed, 1 a check failed, 2 the check could not run.
Standard library only, like csp_smoke.py and protocol_lab_smoke.py, whose static
server, Chrome lookup and DevTools pipe it uses.
"""
from __future__ import annotations

import argparse
import collections
import functools
import http.server
import json
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import csp_smoke  # the static server, the enforced policy, the routes and the Chrome lookup
import protocol_lab_smoke as plab  # the DevTools pipe, the literal reader and the report

ROOT = csp_smoke.ROOT
SRC = ROOT / "services/webui-frontend/src"
#: A tab that animates and polls nothing (measured 2026-11-25: no interval, frame,
#: timer or socket), so what a tab left for it still runs shows up against zero.
QUIET = "/hil"
SETTLE_S = 0.12
ARRIVE_S = 15       # a tab's heading must be drawn this soon after its menu link is pressed
QUIET_S = 1.0       # after a press, wait at most this long for the page's text to stop changing
BUSY_S = 25.0       # ... and this long for its own requests to finish
HANG_S = 30.0       # a page that does not answer a call this long has stopped answering
RUN_S = 1.2         # how long a simulation runs before its tab is left
WINDOW_S = 1.0      # the window measured on QUIET after leaving
SPEED_GAP_S = 0.04
#: Controls that disable one another as a simulation runs: that is the run state, not a busy page.
RUN_CONTROLS = {"Run", "Pause", "Resume", "Abort", "Step", "Reset", "Inject failure"}
EXPORTS = ("Logs", "JSON", "CSV", "PNG")
NOT_PRESSED = r"^(?:Logs|PNG|JSON|CSV|WebM \(HQ\)|GIF|Download plot as a PNG)$"
WRITES = r"^(?:re)?start$|^stop$|\b(?:delete|remove)\b"
ODD = r"\bNaN\b|\bundefined\b|\[object [A-Za-z]+\]|(?<![\w.])-?Infinity\b"


def page_literals() -> dict[str, str]:
    """What the checks compare against, read from the source so a rename cannot drift past them."""
    toolbar = SRC / "components/ExportToolbar.tsx"
    return {
        "crash": plab.literal(SRC / "components/ErrorBoundary.tsx", r"<h2[^>]*>([^<{]+)</h2>"),
        "gallery": plab.literal(toolbar, r'aria-label="([^"]*shared gallery[^"]*)"'),
        "exportFailed": plab.literal(toolbar, r'role="alert">([^{<]+)\{error\}'),
        # The Logs button's tooltip when the tab has no log of its own: it downloads the server's.
        "serverLog": plab.literal(toolbar, r':\s*"(Download rotating server log)"'),
        # What downloadCSV writes for a table with no rows yet.
        "emptyCsv": plab.literal(SRC / "lib/exporters.ts", r'new Blob\(\["([^"\\]+)\\n"\]'),
    }


def toolbar_selects() -> list[str]:
    """The export toolbar's recording selects (duration, WebM and GIF frame rates), from its source.

    The toolbar is one component on every tab, so `controls` sets these on the
    first tab that shows them and leaves them alone after that: some 160 changes
    fewer, the same code.
    """
    found = re.findall(r'aria-label="([^"]+\((?:seconds|fps)\))"', (SRC / "components/ExportToolbar.tsx").read_text())
    if len(found) != 3:
        raise plab.CannotRun(f"ExportToolbar.tsx: expected 3 recording selects, found {found}")
    return found


# Installed before the page's own scripts on every load, in the page's world. It
# counts what the page keeps running, holds back every request but GET and HEAD,
# reads exports instead of saving them, and dispatches the events a reader's input
# would. It waits with the browser's own timers, so it never counts itself.
HELPER = r"""
(() => {
  const CRASH = __CRASH__, GALLERY = __GALLERY__;
  const NOT_PRESSED = new RegExp(__NOT_PRESSED__), WRITES = new RegExp(__WRITES__, "i"), ODD = new RegExp(__ODD__);
  const orig = {
    setInterval: window.setInterval.bind(window), clearInterval: window.clearInterval.bind(window),
    setTimeout: window.setTimeout.bind(window), clearTimeout: window.clearTimeout.bind(window),
    raf: window.requestAnimationFrame.bind(window), fetch: window.fetch.bind(window),
    anchorClick: HTMLAnchorElement.prototype.click, objectURL: URL.createObjectURL.bind(URL),
    xhrOpen: XMLHttpRequest.prototype.open,
  };
  const live = { intervals: new Set(), frames: 0, timers: 0, sockets: new Set(), inflight: 0 };
  window.setInterval = function (...a) { const id = orig.setInterval(...a); live.intervals.add(id); return id; };
  window.clearInterval = function (id) { live.intervals.delete(id); return orig.clearInterval(id); };
  // clearTimeout clears an interval as well: the two share one list of ids.
  window.clearTimeout = function (id) { live.intervals.delete(id); return orig.clearTimeout(id); };
  window.setTimeout = function (...a) { live.timers++; return orig.setTimeout(...a); };
  window.requestAnimationFrame = function (cb) { live.frames++; return orig.raf(cb); };
  if (window.WebSocket) {
    const WS = window.WebSocket;
    window.WebSocket = class extends WS {
      constructor(...a) { super(...a); live.sockets.add(this); this.addEventListener("close", () => live.sockets.delete(this)); }
    };
  }

  const writes = [];
  const NOT_SENT = { detail: "not sent: scripts/spa_tabs_smoke.py lets no request but GET or HEAD leave the page" };
  window.fetch = function (input, init) {
    const req = input instanceof Request ? input : null;
    const method = String((init && init.method) || (req && req.method) || "GET").toUpperCase();
    if (method !== "GET" && method !== "HEAD") {
      writes.push(`${method} ${req ? req.url : String(input)}`);
      return Promise.resolve(new Response(JSON.stringify(NOT_SENT),
        { status: 403, headers: { "Content-Type": "application/json" } }));
    }
    live.inflight++;
    return orig.fetch(input, init).finally(() => { live.inflight--; });
  };
  // The app sends no XMLHttpRequest and no beacon (2026-11-25), so a write by
  // either is refused loudly: the exception is reported, and someone looks at it.
  XMLHttpRequest.prototype.open = function (method, ...rest) {
    if (!/^(GET|HEAD)$/i.test(String(method))) {
      writes.push(`${method} ${rest[0]} (XMLHttpRequest)`);
      throw new Error("spa_tabs_smoke: an XMLHttpRequest write was refused");
    }
    return orig.xhrOpen.call(this, method, ...rest);
  };
  if (navigator.sendBeacon) navigator.sendBeacon = (url) => { writes.push(`BEACON ${url}`); return false; };

  // Exports: exporters.ts makes a Blob, an object URL and an <a download> it clicks.
  // The Blob is kept and the click read here, so nothing is saved.
  const blobs = new Map(), downloads = [];
  URL.createObjectURL = function (obj) { const u = orig.objectURL(obj); if (obj instanceof Blob) blobs.set(u, obj); return u; };
  HTMLAnchorElement.prototype.click = function () {
    if (this.hasAttribute("download")) {
      downloads.push({ name: this.getAttribute("download") || "", blob: blobs.get(this.href) || null,
                       dataUrl: (this.getAttribute("href") || "").startsWith("data:") });
      return;
    }
    return orig.anchorClick.call(this);
  };

  const csp = [];
  document.addEventListener("securitypolicyviolation", (e) =>
    csp.push(`${e.effectiveDirective} refused ${e.blockedURI || "inline"} (${e.sourceFile || "?"}:${e.lineNumber || 0})`));

  const frame = () => new Promise((r) => orig.raf(() => r()));
  const sleep = (ms) => new Promise((r) => orig.setTimeout(r, ms));
  const word = (s) => (s || "").trim().replace(/\s+/g, " ").replace(/^[^A-Za-z0-9(]+/, "");
  // The accessible name, then the visible text, then a tooltip: an export button
  // reads "PNG" and carries its description as a title.
  const labelOf = (el) => word(el.getAttribute("aria-label")
    || (el.labels && el.labels.length ? el.labels[0].textContent : "")
    || el.textContent || el.getAttribute("data-title") || el.getAttribute("title") || el.getAttribute("name") || "");
  const kindOf = (el) => {
    const t = el.tagName;
    if (t === "SELECT") return "select";
    if (t === "TEXTAREA") return "text";
    if (t === "INPUT") {
      if (/^(button|submit|reset)$/i.test(el.type)) return "button";
      return { number: "number", range: "range", checkbox: "checkbox", radio: "checkbox", file: "file", hidden: "hidden" }[el.type] || "text";
    }
    return "button";
  };
  const SELECTOR = "button, select, textarea, input, summary, [role=button]:not(button), [role=tab], [role=switch]";
  const opacity = (el) => { let o = 1; for (let e = el; e && e.tagName !== "MAIN"; e = e.parentElement) o *= Number(getComputedStyle(e).opacity); return o; };
  const enumerate = () => {
    const main = document.querySelector("main");
    if (!main) return [];
    const seen = new Map();
    return [...main.querySelectorAll(SELECTOR)].filter((el) => el.getClientRects().length).map((el) => {
      const kind = kindOf(el), label = labelOf(el);
      // A label that carries a value ("P(intercept) 1.00") keeps its key as the value moves.
      const stem = `${kind}:${label.replace(/[-+]?\d[\d.,]*/g, "#")}`;
      const n = (seen.get(stem) || 0) + 1;
      seen.set(stem, n);
      return { el, key: `${stem}#${n}`, kind, label, text: word(el.textContent) };
    });
  };
  const skipOf = (kind, label, text) => kind === "hidden" ? "a hidden input" : kind === "file" ? "a file chooser"
    : label === GALLERY ? "the shared gallery"
    : kind === "button" && (NOT_PRESSED.test(label) || NOT_PRESSED.test(text)) ? "an export"
    : kind === "button" && (WRITES.test(label) || WRITES.test(text)) ? "a write" : "";
  const find = (key) => { const c = enumerate().find((x) => x.key === key); return c ? c.el : null; };
  const textOf = () => {
    const main = document.querySelector("main");
    if (!main) return "";
    const out = [], w = document.createTreeWalker(main, NodeFilter.SHOW_TEXT);
    for (let t = w.nextNode(); t; t = w.nextNode()) if (t.parentElement && !t.parentElement.closest("select")) out.push(t.textContent);
    return out.join(" ").replace(/\s+/g, " ");
  };

  const tabs = {
    takeCsp() { return csp.splice(0); },
    takeWrites() { return writes.splice(0); },
    crashed() {
      const h = [...document.querySelectorAll('[role="alert"] h2')].find((x) => x.textContent.trim() === CRASH);
      if (!h) return null;
      const p = h.parentElement.querySelector("p");
      return p ? p.textContent.trim() : "(no message)";
    },
    menu() {
      return [...document.querySelectorAll("#site-nav a")].map((a) => ({
        href: a.getAttribute("href"), label: word(a.textContent), current: a.getAttribute("aria-current") === "page" }));
    },
    go(href) {
      const a = [...document.querySelectorAll("#site-nav a")].find((x) => x.getAttribute("href") === href);
      if (!a) throw new Error(`no menu link to ${href}`);
      a.click();
    },
    at() {
      const h = document.querySelector("main h2");
      const cur = [...document.querySelectorAll('#site-nav a[aria-current="page"]')].map((a) => a.getAttribute("href"));
      return { path: location.pathname, heading: h ? word(h.textContent) : null, current: cur, crashed: tabs.crashed() };
    },
    links() {
      const main = document.querySelector("main");
      return main ? [...main.querySelectorAll("a[href]")].map((a) => [a.getAttribute("href"), a.target])
        .filter(([h, t]) => h.startsWith("/") && !h.startsWith("//") && !/^\/(api|ws)(\/|$)/.test(h) && t !== "_blank")
        .map(([h]) => h) : [];
    },
    follow(href) {
      const a = [...document.querySelectorAll("main a[href]")].find((x) => x.getAttribute("href") === href);
      if (!a) throw new Error(`no link to ${href} in the page`);
      a.click();
    },
    controls() {
      return enumerate().map(({ el, key, kind, label, text }) => ({
        key, kind, label, text, title: el.getAttribute("title") || "", skip: skipOf(kind, label, text),
        disabled: Boolean(el.disabled) || el.getAttribute("aria-disabled") === "true",
        opacity: opacity(el), cursor: getComputedStyle(el).cursor,
        value: kind === "checkbox" ? el.checked : (el.value === undefined ? null : el.value),
        min: el.getAttribute("min"), max: el.getAttribute("max"),
        options: kind === "select" ? [...el.options].filter((o) => !o.disabled).map((o) => o.value) : null,
      }));
    },
    enabled(key) { const el = find(key); return el ? !(el.disabled || el.getAttribute("aria-disabled") === "true") : null; },
    press(key) {
      const el = find(key);
      if (!el) return "gone";
      if (el.disabled) return "disabled";
      el.click();
      return "ok";
    },
    control(key) { return tabs.controls().find((c) => c.key === key) || null; },
    choose(key, value) {
      const el = find(key);
      if (!el) return "gone";
      if (![...el.options].some((o) => o.value === value && !o.disabled)) return "absent";
      el.value = value;
      el.dispatchEvent(new Event("change", { bubbles: true }));
      return "ok";
    },
    type(key, value) {
      const el = find(key);
      if (!el) return "gone";
      const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto, "value").set.call(el, String(value));
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
      return "ok";
    },
    oddText() {
      const main = document.querySelector("main");
      if (!main) return [];
      const out = [], w = document.createTreeWalker(main, NodeFilter.SHOW_TEXT);
      for (let t = w.nextNode(); t && out.length < 5; t = w.nextNode()) {
        const el = t.parentElement;
        if (!el || el.closest("pre, code, textarea, select, script, style") || !el.getClientRects().length) continue;
        const s = t.textContent, m = ODD.exec(s);
        if (m) out.push(`${el.tagName.toLowerCase()} "${s.slice(Math.max(0, m.index - 40), m.index + 40).trim()}"`);
      }
      return out;
    },
    alerts() {
      const main = document.querySelector("main");
      return main ? [...main.querySelectorAll('[role="alert"]')].map((a) => a.textContent.trim()).filter(Boolean) : [];
    },
    live() {
      return { intervals: live.intervals.size, frames: live.frames, timers: live.timers, inflight: live.inflight,
               sockets: [...live.sockets].filter((s) => s.readyState < 2).length };
    },
    /** Wait until the page's text stops changing (or `capMs`) and its requests finish (or `busyMs`). */
    async quiet(capMs, busyMs) {
      const t0 = performance.now();
      let last = textOf(), since = performance.now();
      while (performance.now() - t0 < capMs) {
        await sleep(100);
        const now = textOf();
        if (now !== last) { last = now; since = performance.now(); }
        else if (performance.now() - since >= 300 && live.inflight === 0) break;
      }
      while (live.inflight > 0 && performance.now() - t0 < busyMs) await sleep(100);
      return { ms: Math.round(performance.now() - t0), inflight: live.inflight };
    },
    async settle(n = 2) { for (let i = 0; i < n; i++) await frame(); },
    downloads() { return downloads.length; },
    async takeDownloads() {
      const out = [];
      for (const d of downloads.splice(0)) {
        if (!d.blob) { out.push({ name: d.name, size: 0, unread: d.dataUrl ? "a data: URL" : "no Blob behind it" }); continue; }
        const b = d.blob, head = new Uint8Array(await b.slice(0, 8).arrayBuffer());
        const r = { name: d.name, size: b.size, type: b.type, head: [...head].map((x) => x.toString(16).padStart(2, "0")).join("") };
        if (/^(text\/|application\/json)/.test(b.type) || /\.(json|csv|log|txt)$/i.test(d.name)) {
          const text = await b.text(), lines = text.split(/\r?\n/).filter((l) => l.trim());
          r.lines = lines.length;
          r.fields = lines.length ? lines[0].split(",").length : 0;
          r.first = lines.length ? lines[0].slice(0, 120) : "";
          if (/\.json$/i.test(d.name) || b.type === "application/json") {
            try {
              const v = JSON.parse(text);
              r.json = Array.isArray(v) ? `an array of ${v.length}` : v && typeof v === "object" ? `an object of ${Object.keys(v).length} keys` : typeof v;
            } catch (e) { r.jsonError = String(e).slice(0, 120); }
          }
        }
        if (r.head.startsWith("89504e47")) {
          try { const bmp = await createImageBitmap(b); r.png = [bmp.width, bmp.height]; bmp.close(); }
          catch (e) { r.pngError = String(e).slice(0, 120); }
        }
        out.push(r);
      }
      blobs.clear();
      return out;
    },
    // For the self-check: one of each thing the checks look for.
    plantText() {
      const s = document.createElement("span");
      s.id = "spa-tabs-smoke-planted";
      s.textContent = "planted NaN";
      document.querySelector("main").appendChild(s);
    },
    unplantText() { const s = document.getElementById("spa-tabs-smoke-planted"); if (s) s.remove(); },
    plantTimer() { tabs.planted = window.setInterval(() => {}, 250); },
    unplantTimer() { window.clearInterval(tabs.planted); },
    async plantWrite() { return (await window.fetch("/api/spa-tabs-smoke-planted", { method: "POST" })).status; },
  };
  window.__tabs = tabs;
})();
"""


class Hung(Exception):
    """The page stopped answering: its main thread went into something and did not come back."""


class Tabs:
    """The one browser tab the checks drive, and what it reported since the last look."""

    def __init__(self, cdp: plab.Chrome, base: str, lit: dict[str, str], served_here: bool):
        self.cdp, self.base, self.lit, self.served_here = cdp, base, lit, served_here
        self.source = HELPER
        for k, v in (("__CRASH__", lit["crash"]), ("__GALLERY__", lit["gallery"]), ("__NOT_PRESSED__", NOT_PRESSED),
                     ("__WRITES__", WRITES), ("__ODD__", ODD)):
            self.source = self.source.replace(k, json.dumps(v))
        self._open()

    def _open(self) -> None:
        t = self.cdp.send("Target.createTarget", {"url": "about:blank"})
        self.target = t["targetId"]
        self.s = self.cdp.send("Target.attachToTarget", {"targetId": self.target, "flatten": True})["sessionId"]
        for m in ("Page.enable", "Runtime.enable", "Log.enable"):
            self.cdp.send(m, session=self.s)
        self.cdp.send("Page.addScriptToEvaluateOnNewDocument", {"source": self.source}, session=self.s)

    def reopen(self, path: str) -> None:
        """Close a tab that stopped answering and open `path` in a new one."""
        try:
            self.cdp.send("Target.closeTarget", {"targetId": self.target}, timeout=15)
        except plab.CannotRun:
            pass
        time.sleep(1.0)
        self.cdp.take()
        self._open()
        self.load(path)

    def js(self, expression: str, timeout: float = HANG_S):
        try:
            r = self.cdp.send("Runtime.evaluate", {"expression": expression, "awaitPromise": True,
                                                   "returnByValue": True}, session=self.s, timeout=timeout)
        except plab.CannotRun as e:
            if "no reply" in str(e):
                raise Hung(f"no answer in {timeout:.0f} s") from e
            raise
        if "exceptionDetails" in r:
            d = r["exceptionDetails"]
            raise RuntimeError((d.get("exception") or {}).get("description") or d.get("text", "evaluation failed"))
        return (r.get("result") or {}).get("value")

    def call(self, fn: str, *args, timeout: float = HANG_S):
        return self.js(f"window.__tabs.{fn}({', '.join(json.dumps(a) for a in args)})", timeout)

    def load(self, path: str) -> None:
        self.cdp.send("Page.navigate", {"url": self.base + path}, session=self.s)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                if self.js("Boolean(window.__tabs && window.__tabs.menu().length && window.__tabs.at().heading)"):
                    self.call("settle")
                    return
            except RuntimeError:
                pass
            time.sleep(0.1)
        raise plab.CannotRun(f"{path} did not draw the menu and a heading in 30 s")

    def arrive(self, href: str, before: str | None) -> dict:
        """Wait for `href` to be the path and its heading to be drawn (a new one, if `before` is given)."""
        deadline = time.monotonic() + ARRIVE_S
        at = self.call("at")
        while time.monotonic() < deadline:
            if at["path"] == href and (at["heading"] and at["heading"] != before or at["crashed"]):
                break
            time.sleep(0.05)
            at = self.call("at")
        self.call("settle")
        time.sleep(SETTLE_S)
        return self.call("at")

    def go(self, href: str) -> dict:
        before = self.call("at")
        if before["path"] == href:
            return before
        self.call("go", href)
        return self.arrive(href, before["heading"])

    def window(self) -> dict:
        """What ran on the page during WINDOW_S: intervals and sockets at its end, frames and timers in it."""
        a = self.call("live")
        time.sleep(WINDOW_S)
        b = self.call("live")
        return {"intervals": b["intervals"], "sockets": b["sockets"],
                "frames": b["frames"] - a["frames"], "timers": b["timers"] - a["timers"]}

    def problems(self) -> list[str]:
        """Exceptions, console errors, error-level log entries, CSP violations, the error boundary and odd text since the last call."""
        csp = self.call("takeCsp")
        crash = self.call("crashed")
        odd = self.call("oddText")
        out = []
        for ev in self.cdp.take():
            if ev.get("sessionId") != self.s:
                continue
            p = ev.get("params", {})
            if ev["method"] == "Runtime.exceptionThrown":
                d = p.get("exceptionDetails", {})
                text = (d.get("exception") or {}).get("description") or d.get("text", "")
                out.append(f"exception: {text.splitlines()[0] if text else '?'}")
            elif ev["method"] == "Runtime.consoleAPICalled" and p.get("type") in ("error", "assert"):
                args = " ".join(str(a.get("value", a.get("description", ""))) for a in p.get("args", []))
                out.append(f"console.error: {args.splitlines()[0] if args else ''}")
            elif ev["method"] == "Log.entryAdded" and p.get("entry", {}).get("level") == "error":
                e = p["entry"]
                if "Content Security Policy" in e.get("text", ""):
                    continue  # counted once, by the securitypolicyviolation listener
                if self.served_here and e.get("source") == "network" and re.search(r"/(api|ws)(/|$)", e.get("url", "")):
                    continue  # no backend in this check (csp_smoke.py): /api and /ws answer 404
                url = e.get("url", "")
                out.append(f"log ({e.get('source')}): {e.get('text', '')[:140]}{' ' + url[-80:] if url else ''}")
        out += [f"csp: {v}" for v in csp]
        if crash:
            out.append(f"error boundary: {crash}")
        out += [f"text a reader should not see: {o}" for o in odd]
        return out

    def self_check(self) -> list[str]:
        """Plant one of each failure the checks look for; all must be seen. Returns what else was reported."""
        self.go(QUIET)
        time.sleep(0.5)
        base = self.window()
        self.js("setTimeout(() => { throw new Error('spa-tabs-smoke planted exception'); }, 0);"
                "console.error('spa-tabs-smoke planted console error');"
                "new Image().src = 'https://spa-tabs-smoke.invalid/planted.png'; 0")
        self.call("plantText")
        time.sleep(0.4)
        found = self.problems()
        self.call("unplantText")
        status = self.call("plantWrite")
        held = self.call("takeWrites")
        self.call("plantTimer")
        timed = self.window()
        self.call("unplantTimer")
        need = {"exception": "planted exception", "console error": "planted console error",
                "CSP violation": "spa-tabs-smoke.invalid", "text a reader should not see": "planted NaN"}
        missing = [k for k, v in need.items() if not any(v in f for f in found)]
        if status != 403 or not any("spa-tabs-smoke-planted" in w for w in held):
            missing.append(f"held-back write (status {status}, held {held})")
        if timed["intervals"] != base["intervals"] + 1:
            missing.append(f"interval left running ({base['intervals']} -> {timed['intervals']})")
        if missing:
            raise plab.CannotRun(f"a planted {', '.join(missing)} was not seen, so a real one would not be")
        return [f for f in found if not any(v in f for v in need.values())]


def number(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def show(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


def values_for(c: dict) -> list[str]:
    """For a number or a range: its limits, a value between, past each limit, nothing; then back."""
    lo, hi, v0 = number(c["min"]), number(c["max"]), number(c["value"])
    out: list[str] = []
    if lo is not None:
        out.append(show(lo))
    if hi is not None:
        out.append(show(hi))
    if lo is not None and hi is not None:
        out.append(show((lo + hi) / 2))
    elif v0 is not None:
        out.append(show(v0 * 2 if v0 else 1))
    if c["kind"] == "number":
        out.append("")
        if lo is not None:
            out.append(show(lo - 1))
        if hi is not None:
            out.append(show(hi + 1))
    out.append(c["value"] if c["value"] is not None else "")
    return out


def recover(t: Tabs, href: str) -> None:
    """After the error boundary, leave and come back: the boundary is keyed on the path."""
    t.go(QUIET if href != QUIET else "/")
    t.go(href)


def exercise(t: Tabs, href: str, c: dict) -> tuple[int, list[str]]:
    """Use one control the ways a reader can. Returns (actions, problems, each prefixed with what was done).

    A page that stops answering is the finding, not a reason to stop: it is
    reported with what was done last, and the tab is opened afresh.
    """
    doing = {"what": "reached"}
    try:
        return _exercise(t, href, c, doing)
    except Hung as e:
        t.reopen(href)
        return 1, [f"{c['label']!r} {doing['what']}: the page stopped answering ({e})"]


def _exercise(t: Tabs, href: str, c: dict, doing: dict) -> tuple[int, list[str]]:
    key, kind = c["key"], c["kind"]
    bad: list[str] = []

    def after(what: str, wait: bool = False) -> None:
        doing["what"] = what
        if wait:
            t.call("quiet", int(QUIET_S * 1000), int(BUSY_S * 1000), timeout=BUSY_S + 30)
        else:
            t.call("settle")
            time.sleep(SETTLE_S)
        found = t.problems()
        bad.extend(f"{c['label']!r} {what}: {p}" for p in found)
        if any(p.startswith("error boundary") for p in found):
            recover(t, href)

    if kind == "button":
        doing["what"] = "pressed"
        r = t.call("press", key)
        if r != "ok":
            return 0, []
        after("pressed", wait=c["label"] not in RUN_CONTROLS)
        return 1, bad
    if kind == "select":
        values = [v for v in c["options"] if v != c["value"]] + [c["value"]]
        for v in values:
            doing["what"] = f"set to {v!r}"
            if t.call("choose", key, v) != "ok":
                break
            after(f"set to {v!r}", wait=True)
        return len(values), bad
    if kind in ("number", "range"):
        values = values_for(c)
        for v in values:
            doing["what"] = f"set to {v!r}"
            if t.call("type", key, v) != "ok":
                break
            after(f"set to {v!r}", wait=True)
        return len(values), bad
    if kind == "checkbox":
        for what in ("ticked", "cleared"):
            if t.call("press", key) != "ok":
                break
            after(what, wait=True)
        return 2, bad
    if kind == "text":
        for v in ("spa-tabs-smoke", c["value"] or ""):
            if t.call("type", key, v) != "ok":
                break
            after(f"set to {v!r}", wait=True)
        return 2, bad
    return 0, []


def arrival_problems(href: str, at: dict, before: str | None, crash: str) -> list[str]:
    bad = []
    if at["path"] != href:
        bad.append(f"the path is {at['path']}, not {href}")
    if at["current"] != [href]:
        bad.append(f"the menu marks {at['current']} as current, not [{href!r}]")
    if not at["heading"] or at["heading"] == crash:
        bad.append(f"no heading drawn: {at['heading']!r}")
    elif before is not None and at["heading"] == before:
        bad.append(f"the heading is still the last tab's: {before!r}")
    return bad


# --- tabs (4.3.8) -------------------------------------------------------------------------------------

def check_tabs(t: Tabs, rep: plab.Report, menu: list[str]) -> None:
    print("tabs: the menu forward, backward and at speed, then the links inside pages")
    for walk, seq in (("forward", menu), ("backward", menu[::-1])):
        t.go(seq[-1])
        failed = 0
        for href in seq:
            before = t.call("at")["heading"]
            t.call("go", href)
            at = t.arrive(href, before)
            ok = rep.check(f"{walk}: {href}", t.problems() + arrival_problems(href, at, before, t.lit["crash"]), quiet=True)
            failed += not ok
        print(f"  {walk + ':':<48} {'ok  ' if not failed else 'FAIL'} {len(seq)} tabs, {failed} failed")
    for walk, seq in (("at speed, forward", menu), ("at speed, backward", menu[::-1])):
        t.go(seq[0])
        for href in seq[1:]:
            t.call("go", href)
            time.sleep(SPEED_GAP_S)
        at = t.arrive(seq[-1], None)
        time.sleep(0.5)
        rep.check(walk, t.problems() + arrival_problems(seq[-1], at, None, t.lit["crash"]),
                  f"{len(seq)} links, {SPEED_GAP_S * 1000:.0f} ms apart, ending on {seq[-1]}")
    followed = 0
    for href in menu:
        t.go(href)
        for link in dict.fromkeys(t.call("links")):
            try:
                t.go(href)
                before = t.call("at")["heading"]
                t.call("follow", link)
                path = link.split("?")[0].split("#")[0]
                at = t.arrive(path, before if path != href else None)
                rep.check(f"{href}: its link to {link}",
                          t.problems() + arrival_problems(path, at, None, t.lit["crash"]), quiet=True)
                followed += 1
            except Hung as e:
                rep.check(f"{href}: its link to {link}", [f"the page stopped answering ({e})"])
                t.reopen(href)
    print(f"  {'links inside pages to other tabs:':<48} ok   {followed} followed")


# --- controls (4.3.9) ---------------------------------------------------------------------------------

def check_controls(t: Tabs, rep: plab.Report, menu: list[str]) -> None:
    print("controls: every control on every tab")
    total = 0
    shared = dict.fromkeys(toolbar_selects(), "")  # label -> the tab they were set on
    for href in menu:
        t.go(href)
        done: set[str] = set()
        once: set[str] = set()
        bad: list[str] = []
        looks: dict[str, str] = {}
        actions = 0
        for _ in range(4):  # a later round for what an earlier one enabled or revealed
            progressed = False
            for key in [c["key"] for c in t.call("controls")]:
                # Read it again: an earlier control may have changed it (a network
                # changes which nodes a demand can name) or removed it.
                c = None if key in done else t.call("control", key)
                if not c or c["skip"]:
                    continue
                if c["kind"] == "select" and shared.get(c["label"], href) not in ("", href):
                    once.add(c["label"])
                    continue
                if c["disabled"]:
                    if not (c["opacity"] < 1 and c["cursor"] == "not-allowed"):
                        looks[c["key"]] = f"opacity {c['opacity']:.2f}, cursor {c['cursor']}"
                    continue
                n, found = exercise(t, href, c)
                if c["kind"] == "select" and c["label"] in shared:
                    shared[c["label"]] = href
                done.add(c["key"])
                actions += n
                bad += found
                progressed = True
            if not progressed:
                break
        t.call("quiet", int(QUIET_S * 1000), int(BUSY_S * 1000), timeout=BUSY_S + 30)
        time.sleep(1.0)
        bad += [f"after its controls: {p}" for p in t.problems()]
        bad += [f"{k} is disabled but does not look it ({v})" for k, v in looks.items()]
        last = t.call("controls")
        skipped = collections.Counter(c["skip"] for c in last if c["skip"])
        never = sorted({c["label"] for c in last if not c["skip"] and c["key"] not in done and c["label"] not in once})
        detail = f"{len(done)} controls, {actions} actions"
        if once:
            skipped[f"of the toolbar's recording selects (set on {shared[next(iter(once))]})"] = len(once)
        if skipped:
            detail += "; left alone: " + ", ".join(f"{n} {why}" for why, n in sorted(skipped.items()))
        if never:
            detail += f"; never enabled: {', '.join(never)}"
        rep.check(href, bad, detail)
        total += actions
    print(f"  {total} actions in all")


# --- leave (4.3.10) -----------------------------------------------------------------------------------

def check_leave(t: Tabs, rep: plab.Report, menu: list[str]) -> None:
    t.go(QUIET)
    time.sleep(0.8)
    base = t.window()
    print(f"leave: each tab, running where it can, left for {QUIET}, which runs "
          f"{base['intervals']} intervals, {base['frames']} frames and {base['timers']} timers in {WINDOW_S:g} s, "
          f"{base['sockets']} sockets")
    for href in menu:
        if href == QUIET:
            continue
        try:
            leave_one(t, rep, href, base)
        except Hung as e:
            rep.check(f"{href}, left for {QUIET}", [f"the page stopped answering ({e})"])
            t.reopen(QUIET)


def leave_one(t: Tabs, rep: plab.Report, href: str, base: dict) -> None:
    t.go(href)
    run = next((c for c in t.call("controls") if c["kind"] == "button" and c["label"] == "Run" and not c["disabled"]), None)
    if run:
        t.call("press", run["key"])
    time.sleep(RUN_S)
    there = t.window()
    t.go(QUIET)
    time.sleep(0.8)
    left = t.window()
    bad = t.problems()
    if left["intervals"] > base["intervals"]:
        bad.append(f"{left['intervals'] - base['intervals']} interval(s) still set on {QUIET}")
    if left["sockets"] > base["sockets"]:
        bad.append(f"{left['sockets'] - base['sockets']} socket(s) still open on {QUIET}")
    if left["frames"] > base["frames"] + 1:
        bad.append(f"{left['frames']} animation frames in {WINDOW_S:g} s on {QUIET}, which draws {base['frames']}")
    if left["timers"] > base["timers"] + 1:
        bad.append(f"{left['timers']} timers set in {WINDOW_S:g} s on {QUIET}, which sets {base['timers']}")
    rep.check(f"{href}{' running' if run else ''}, left for {QUIET}", bad,
              f"there {there['frames']} frames, {there['timers']} timers, {there['intervals']} intervals, "
              f"{there['sockets']} sockets; after: {left['frames']}, {left['timers']}, {left['intervals']}, {left['sockets']}")


# --- exports (4.3.11) ---------------------------------------------------------------------------------

def file_problems(label: str, f: dict, empty_csv: str) -> list[str]:
    if f.get("unread"):
        return [f"{f['name']}: {f['unread']}"]
    if f["size"] <= 0:
        return [f"{f['name']} is empty"]
    if label == "Logs" and not f.get("lines"):
        return [f"{f['name']} has no line of text"]
    if label == "JSON" and "json" not in f:
        return [f"{f['name']} does not parse: {f.get('jsonError', 'not read as text')}"]
    if label == "CSV" and f.get("lines") == 1 and f.get("first") == empty_csv:
        return []  # a table with no rows yet, said in the file
    if label == "CSV" and (f.get("lines", 0) < 2 or f.get("fields", 0) < 2):
        return [f"{f['name']}: {f.get('lines', 0)} lines, {f.get('fields', 0)} fields in the first: {f.get('first', '')!r}"]
    if label == "PNG" and not (f.get("png") and f["png"][0] > 0 and f["png"][1] > 0):
        return [f"{f['name']} is not a PNG that decodes: head {f.get('head')} {f.get('pngError', '')}"]
    return []


def describe(label: str, f: dict, empty_csv: str) -> str:
    if label == "PNG" and f.get("png"):
        return f"PNG {f['png'][0]}x{f['png'][1]}"
    if label == "JSON" and f.get("json"):
        return f"JSON {f['json']}"
    if label == "CSV" and f.get("first") == empty_csv and f.get("lines") == 1:
        return f"CSV {empty_csv!r} (no rows yet)"
    if label == "CSV":
        return f"CSV {f.get('lines')} lines x {f.get('fields')}"
    return f"{label} {f['size']} B"


def check_exports(t: Tabs, rep: plab.Report, menu: list[str]) -> None:
    print("exports: Logs, JSON, CSV and PNG on every tab that offers them")
    tabs_with = 0
    for href in menu:
        try:
            tabs_with += export_one(t, rep, href)
        except Hung as e:
            rep.check(f"{href}: exports", [f"the page stopped answering ({e})"])
            tabs_with += 1
            t.reopen(href)
    if not tabs_with:
        rep.check("exports: some tab offers them", ["no tab has an export button: the labels moved"])


def export_one(t: Tabs, rep: plab.Report, href: str) -> int:
    """The exports of one tab; 1 if it has any, else 0."""
    t.go(href)
    cs = t.call("controls")
    present = [c for c in cs if c["kind"] == "button" and c["text"] in EXPORTS]
    if not present:
        return 0
    bad: list[str] = []
    gallery = next((c for c in cs if c["label"] == t.lit["gallery"]), None)
    if gallery and gallery["value"]:
        rep.check(f"{href}: exports", [f"{t.lit['gallery']!r} is ticked when the tab opens"])
        return 1
    # Something to export: three Steps where the tab steps, else one press of
    # its own "Run ..." button (/pqc's "Run round-trips"), as a reader would.
    step = next((c for c in cs if c["kind"] == "button" and c["label"] == "Step" and not c["disabled"]), None)
    runs = None if step else next((c for c in cs if c["kind"] == "button" and not c["disabled"] and not c["skip"]
                                   and c["label"].startswith("Run ")), None)
    if step:
        for _ in range(3):
            t.call("press", step["key"])
            t.call("settle")
            time.sleep(0.4)
    elif runs:
        t.call("press", runs["key"])
        t.call("quiet", int(QUIET_S * 1000), int(BUSY_S * 1000), timeout=BUSY_S + 30)
    t.call("takeDownloads")
    made = []
    for c in present:
        if t.served_here and c["text"] == "Logs" and c["title"] == t.lit["serverLog"]:
            made.append("Logs is the server's log here: not without a backend (--base reads it)")
            continue
        if not t.call("enabled", c["key"]):
            made.append(f"{c['text']} disabled")
            continue
        t.call("press", c["key"])
        deadline = time.monotonic() + 20
        while t.call("downloads") == 0 and time.monotonic() < deadline:
            time.sleep(0.1)
        time.sleep(0.2)
        files = t.call("takeDownloads")
        if len(files) != 1:
            bad.append(f"{c['text']} made {len(files)} files, not 1: {[f['name'] for f in files]}")
        for f in files:
            bad += [f"{c['text']}: {p}" for p in file_problems(c["text"], f, t.lit["emptyCsv"])]
        if files:
            made.append(describe(c["text"], files[0], t.lit["emptyCsv"]))
    failed = [a for a in t.call("alerts") if a.startswith(t.lit["exportFailed"].rstrip())]
    bad += [f"the toolbar reads {a!r}" for a in failed] + t.problems()
    first = " after 3 Steps" if step else f" after {runs['label']!r}" if runs else ""
    rep.check(f"{href}: exports{first}", bad, "; ".join(made))
    return 1


PHASES = {"tabs": check_tabs, "controls": check_controls, "leave": check_leave, "exports": check_exports}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dist", type=Path, default=ROOT / "services/webui-frontend/dist")
    ap.add_argument("--caddyfile", type=Path, default=ROOT / "deploy/Caddyfile")
    ap.add_argument("--app", type=Path, default=SRC / "App.tsx")
    ap.add_argument("--policy", help="serve this policy instead of the Caddyfile's (to show the gate fails)")
    ap.add_argument("--base", help="drive this deployed origin (https://...) instead of serving --dist")
    ap.add_argument("--chrome", help="path to Chrome or Chromium (default: first one on PATH)")
    ap.add_argument("--no-sandbox", action="store_true", help="pass --no-sandbox to Chrome (CI runners)")
    ap.add_argument("--only", default=",".join(PHASES), help=f"comma-separated subset of {','.join(PHASES)}")
    ap.add_argument("--tabs", help="comma-separated paths: check only these tabs (all by default)")
    a = ap.parse_args()
    sys.stdout.reconfigure(line_buffering=True)  # a CI log shows each line as it is checked
    phases = [p.strip() for p in a.only.split(",") if p.strip()]
    if not phases or any(p not in PHASES for p in phases):
        print(f"error: --only takes {','.join(PHASES)}", file=sys.stderr)
        return 2

    try:
        lit = page_literals()
        routes = csp_smoke.routes(a.app)
        if QUIET not in routes:
            raise plab.CannotRun(f"{QUIET}, the tab `leave` measures on, is no longer a route in {a.app.name}")
        chrome = csp_smoke.find_chrome(a.chrome)
        if not chrome:
            raise plab.CannotRun("no Chrome or Chromium found")
        policy = None
        if not a.base:
            if not (a.dist.resolve() / "index.html").is_file():
                raise plab.CannotRun(f"no build at {a.dist} (run `npx vite build` in services/webui-frontend)")
            policy = a.policy or csp_smoke.enforced_policy(a.caddyfile)
            if not policy:
                raise plab.CannotRun(f"{a.caddyfile} has no single enforced Content-Security-Policy line")
        version = subprocess.run([chrome, "--version"], capture_output=True, text=True).stdout.strip()
    except plab.CannotRun as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    rep = plab.Report()
    server = None
    with tempfile.TemporaryDirectory(prefix="spa-tabs-smoke-") as tmp:
        cdp = plab.Chrome(chrome, Path(tmp) / "profile", a.no_sandbox)  # before the server's thread
        try:
            if a.base:
                base = a.base.rstrip("/")
            else:
                server = http.server.ThreadingHTTPServer(
                    ("127.0.0.1", 0), functools.partial(csp_smoke.Handler, policy=policy, dist=a.dist.resolve()))
                threading.Thread(target=server.serve_forever, daemon=True).start()
                base = f"http://127.0.0.1:{server.server_address[1]}"
            t = Tabs(cdp, base, lit, served_here=not a.base)
            t.load("/")
            menu = [m["href"] for m in t.call("menu")]
            where = "the deployed page" if a.base else f"policy {'from --policy' if a.policy else 'from Caddyfile'}"
            print(f"{version}; {len(menu)} tabs; {where}")
            loaded = t.problems()
            rep.check("the menu links every route, once", [
                *(f"no menu link to {r}" for r in routes if r not in menu),
                *(f"a menu link to {m}, which is no route" for m in menu if m not in routes),
                *(f"{m} is linked {n} times" for m, n in collections.Counter(menu).items() if n > 1)])
            if a.tabs:
                wanted = [x.strip() for x in a.tabs.split(",") if x.strip()]
                unknown = [x for x in wanted if x not in menu]
                if unknown:
                    raise plab.CannotRun(f"--tabs names no menu link: {unknown}")
                menu = [m for m in menu if m in wanted]
            loaded += t.self_check()
            print("planted exception, console error, CSP violation, odd text, held-back write and timer: all seen")
            rep.check("/ loads", loaded)
            started = time.monotonic()
            for p in phases:
                PHASES[p](t, rep, menu)
            held = collections.Counter(re.sub(r"https?://[^/]+", "", w) for w in t.call("takeWrites"))
            if held:
                print(f"held back in the page, never sent: {'; '.join(f'{w} x{n}' for w, n in sorted(held.items()))}")
            print(f"{rep.passed + len(rep.failed)} checks, {len(rep.failed)} failed, "
                  f"{time.monotonic() - started:.0f} s")
        except plab.CannotRun as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        finally:
            cdp.close()
            if server:
                server.shutdown()
    return 1 if rep.failed else 0


if __name__ == "__main__":
    sys.exit(main())
