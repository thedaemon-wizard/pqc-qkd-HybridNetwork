#!/usr/bin/env python3
"""Drive the Protocol Lab in headless Chrome and fail on what a reader would hit.

scripts/csp_smoke.py opens every route once. This one plays /protocol-lab the
way a reader does -- Step, Run, Pause, the speed, failures, the network and
scenario selects -- through the DevTools protocol on a pipe, on the same build
and under the same enforced Content-Security-Policy (deploy/Caddyfile):

  networks  every published network in free play and every cited scenario,
            stepped, then read back: the band, the counters and the supply
            line must agree with each other and with the rate the page cites
            (VERIFICATION_CHECKLIST row 4.4c.25)
  controls  Run, Pause, Step while paused, Resume, a change of speed while
            running, Reset; a failure injected on the route and cleared, a
            random outage, another demand; each scenario's own events (4.4c.26)
  switches  the network or the scenario changed with one select while a tick
            plays -- at every part of a Step's playback, and at the last part
            of a Run's -- for every change one select can make, and no tick
            after it (4.4c.27). Until PR #152 such a change could leave the
            page on its error boundary.

Every check fails on the page's error boundary, an uncaught exception, a
console error, a CSP violation, or a band that does not begin with the
simulation notice. Those literals are read from the source, and each run first
plants an exception, a console error and a CSP violation and requires all
three to be seen, so a run that could not see a failure cannot pass.

    npx vite build                      # in services/webui-frontend
    python3 scripts/protocol_lab_smoke.py
    python3 scripts/protocol_lab_smoke.py --base https://<the demo's host>

--base drives the deployed page instead (after a deploy): nothing is served
from here and the policy is whatever the host sends. The check never exports,
so it never reaches the shared-gallery upload.

Exit status: 0 every check passed, 1 a check failed, 2 the check could not run.
Standard library only, like csp_smoke.py, whose server and Chrome lookup it uses.
"""
from __future__ import annotations

import argparse
import fcntl
import functools
import http.server
import json
import math
import os
import re
import select
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import csp_smoke  # the static server, the enforced policy and the Chrome lookup

ROOT = csp_smoke.ROOT
SRC = ROOT / "services/webui-frontend/src"
PAGE = "/protocol-lab"
# A Step plays for at least STEP_MIN_PLAY_MS (playback.ts, 1200 ms); a Run's
# first tick comes one dwell after Run at most (1.2 s at the Normal speed).
STEP_PLAY_WAIT_MS = 1600
RUN_PLAY_WAIT_MS = 4000
PART_TRIES = 3
SETTLE_S = 0.12
PLANT_WAIT_S = 15.0  # how long the self-check waits, at most, for what it planted
# What a cited replay must show once stepped past its end, from its source.
REPLAYS = {
    # Peev et al. 2009, section 5.1.2: the three published routes in turn, then none.
    "secoqc-reroute-2008": {"route": "Route: none", "changes": "3"},
    # Dynes et al. 2019, Fig. 3: no key request fails, the outage included.
    "cambridge-otp-reroute-2019": {"failed": 0},
}
# "Supply: this route's slowest hop, SND-ERF, reports average 12.7 ± 10.3 bps; at that
# rate it makes one 256-bit key about every 20 s (derived, at 256 bits per key ...)."
# The reported value keeps the source's wording ("about 2.1 kbps", "almost equal to
# the SECOQC criterion of 1 kbit/s"); its first number with a unit is the rate.
SUPPLY_RE = re.compile(r"slowest hop, (\S+), reports [^;]*?([\d.]+)\s*(?:±\s*[\d.]+\s*)?([kMG]?)(?:bps|bit/s)"
                       r"; at that rate it makes (?:about ([\d.]+) keys/s|one \d+-bit key about every ([\d.]+) s)"
                       r".*?at (\d+) bits per key")
PREFIX = {"": 1, "k": 1e3, "M": 1e6, "G": 1e9}


def supply_of(text: str | None) -> tuple[str, float, int, float] | None:
    """(slowest hop, its reported bps, bits per key, the keys/s the page derives) from the supply line."""
    m = SUPPLY_RE.search(text or "")
    if not m:
        return None
    derived = float(m.group(4)) if m.group(4) else 1 / float(m.group(5))
    return m.group(1), float(m.group(2)) * PREFIX[m.group(3)], int(m.group(6)), derived


class CannotRun(Exception):
    """The check could not run (exit 2), as opposed to a check that failed."""


def literal(path: Path, pattern: str) -> str:
    m = re.search(pattern, path.read_text())
    if not m:
        raise CannotRun(f"{path.relative_to(ROOT)}: no match for {pattern!r}")
    return m.group(1).strip()


def page_literals() -> dict[str, str]:
    """What the page renders that the checks compare against, read from its source."""
    topo = SRC / "components/LiveTopology.tsx"
    return {
        "crash": literal(SRC / "components/ErrorBoundary.tsx", r"<h2[^>]*>([^<{]+)</h2>"),
        "band": literal(topo, r"`([^`$]*running stack[^`$]*)\$\{notes\}`"),
        "routeOnly": literal(topo, r'export const ROUTE_ONLY_NOTE = "([^"]+)"'),
    }


class Chrome:
    """Headless Chrome on --remote-debugging-pipe: it reads commands on fd 3, writes on fd 4.

    Started before any thread exists: the child moves the two pipe ends to 3
    and 4 between fork and exec, which is only safe in a single-threaded parent.
    """

    def __init__(self, exe: str, profile: Path, no_sandbox: bool):
        cmd_r, self._w = os.pipe()
        self._r, evt_w = os.pipe()
        keep = [fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, 10) for fd in (cmd_r, evt_w)]
        os.close(cmd_r)
        os.close(evt_w)

        def wire() -> None:
            os.dup2(keep[0], 3)
            os.dup2(keep[1], 4)

        args = [exe, "--headless=new", "--remote-debugging-pipe", "--disable-gpu", "--no-first-run",
                "--no-default-browser-check", "--disable-extensions", "--mute-audio",
                "--window-size=1280,1000", f"--user-data-dir={profile}", "about:blank"]
        if no_sandbox:
            args.insert(1, "--no-sandbox")
        # close_fds=False: every other descriptor here is close-on-exec (PEP 446),
        # and pass_fds would require 3 and 4 to be open in this process.
        self.proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, close_fds=False, preexec_fn=wire)
        for fd in keep:
            os.close(fd)
        self._buf = b""
        self._id = 0
        self.events: list[dict] = []

    def _read(self, deadline: float) -> list[dict]:
        out = []
        while not out:
            left = deadline - time.monotonic()
            if left <= 0 or not select.select([self._r], [], [], left)[0]:
                return out
            chunk = os.read(self._r, 1 << 20)
            if not chunk:
                raise CannotRun("Chrome closed the DevTools pipe")
            self._buf += chunk
            *whole, self._buf = self._buf.split(b"\0")
            out = [json.loads(m) for m in whole if m]
        return out

    def send(self, method: str, params: dict | None = None, session: str | None = None,
             timeout: float = 30) -> dict:
        self._id += 1
        msg: dict = {"id": self._id, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        data = json.dumps(msg).encode() + b"\0"
        while data:
            data = data[os.write(self._w, data):]
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for m in self._read(deadline):
                if m.get("id") == self._id:
                    if "error" in m:
                        raise CannotRun(f"{method}: {m['error'].get('message')}")
                    return m.get("result", {})
                if "method" in m:
                    self.events.append(m)
        raise CannotRun(f"{method}: no reply in {timeout:.0f} s")

    def take(self) -> list[dict]:
        """The events that came in with the replies so far; clears the list."""
        out, self.events = self.events, []
        return out

    def close(self) -> None:
        try:
            self.send("Browser.close", timeout=5)
        except (CannotRun, OSError):
            pass
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        for fd in (self._r, self._w):
            os.close(fd)


# Installed before the page's own scripts on every load, in the page's world:
# it only reads the DOM and dispatches the events a reader's input would.
HELPER = r"""
(() => {
  const CRASH = __CRASH__, BAND = __BAND__;
  const csp = [];
  document.addEventListener("securitypolicyviolation", (e) =>
    csp.push(`${e.effectiveDirective} refused ${e.blockedURI || "inline"} (${e.sourceFile || "?"}:${e.lineNumber || 0})`));
  const sel = (aria) => document.querySelector(`select[aria-label="${aria}"]`);
  const word = (b) => (b.textContent || "").trim().replace(/^[^A-Za-z0-9]+/, "");
  const frame = () => new Promise((r) => requestAnimationFrame(() => r()));
  const lab = {
    takeCsp() { return csp.splice(0); },
    ready() { return Boolean(sel("Published network") && document.querySelector("#protocol-lab-topology-svg")); },
    button(label) { return [...document.querySelectorAll("button")].find((b) => word(b) === label) || null; },
    click(label) {
      const b = lab.button(label);
      if (!b) throw new Error(`no "${label}" button`);
      if (b.disabled) throw new Error(`"${label}" is disabled`);
      b.click();
    },
    choose(aria, value) {
      const s = sel(aria);
      if (!s) throw new Error(`no "${aria}" select`);
      if (![...s.options].some((o) => o.value === value)) throw new Error(`"${aria}" offers no "${value}"`);
      s.value = value;
      s.dispatchEvent(new Event("change", { bubbles: true }));
    },
    options(aria) { const s = sel(aria); return s ? [...s.options].map((o) => [o.value, o.textContent]) : []; },
    typeNumber(aria, value) {
      const i = document.querySelector(`input[aria-label="${aria}"]`);
      if (!i) throw new Error(`no "${aria}" input`);
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(i, String(value));
      i.dispatchEvent(new Event("input", { bubbles: true }));
    },
    band() {
      const svg = document.querySelector("#protocol-lab-topology-svg");
      return svg ? [...svg.querySelectorAll("text")].map((t) => t.textContent || "")
        .filter((t) => t.startsWith(BAND) || t.startsWith("t = ") || t.startsWith("Route: ")) : [];
    },
    crashed() {
      const h = document.querySelector('[role="alert"] h2');
      if (!h || h.textContent.trim() !== CRASH) return null;
      const p = h.parentElement.querySelector("p");
      return p ? p.textContent.trim() : "(no message)";
    },
    kpi(label) {
      const el = [...document.querySelectorAll("div")]
        .find((d) => d.children.length === 0 && (d.textContent || "").trim() === label);
      return el && el.nextElementSibling ? el.nextElementSibling.textContent.trim() : null;
    },
    eventButtons() {
      const row = sel("Failure target")?.parentElement;
      const all = row ? [...row.querySelectorAll("button")].map(word) : [];
      const i = all.indexOf("Clear failures");
      return i < 0 ? [] : all.slice(i + 1);
    },
    read() {
      const strip = [...document.querySelectorAll("span")]
        .find((s) => (s.textContent || "").startsWith("status: "));
      const m = strip ? /^status: (\w+); tick (\d+) = ([\d.]+) s each/.exec(strip.textContent) : null;
      const supply = [...document.querySelectorAll("div")]
        .find((d) => (d.textContent || "").startsWith("Supply: "));
      const text = document.body.textContent || "";
      return {
        band: lab.band(), crashed: lab.crashed(),
        status: m ? m[1] : null, tick: m ? Number(m[2]) : null,
        network: sel("Published network")?.value ?? null, scenario: sel("Cited scenario")?.value ?? null,
        requests: lab.kpi("Requests ok / failed"), routeChanges: lab.kpi("Route changes"),
        supply: supply ? supply.textContent.trim() : null,
        routeOnlyNote: text.includes("Nothing is generated or relayed here"),
        keyLegend: text.includes("key crossing a link under that hop's pad"),
      };
    },
    async settle(n = 3) { for (let i = 0; i < n; i++) await frame(); },
    async steps(n) { for (let i = 0; i < n; i++) lab.click("Step"); await lab.settle(); },
    /**
     * Start a tick with `drive` ("Step", "Run", or "" to wait on one already
     * playing) and change the select in the frame whose band shows `part`.
     */
    switchAt(part, drive, aria, value, waitMs) {
      return new Promise((resolve) => {
        const t0 = performance.now();
        const seen = new Set();
        const look = () => {
          const m = /; now (\d+) of (\d+), /.exec(lab.band()[1] || "");
          if (m) seen.add(Number(m[1]));
          if (m && Number(m[1]) === part) {
            try { lab.choose(aria, value); resolve({ done: true, seen: [...seen] }); }
            catch (e) { resolve({ done: false, error: String(e), seen: [...seen] }); }
          } else if (performance.now() - t0 > waitMs) {
            resolve({ done: false, seen: [...seen] });
          } else {
            requestAnimationFrame(look);
          }
        };
        try { if (drive) lab.click(drive); } catch (e) { resolve({ done: false, error: String(e), seen: [] }); return; }
        requestAnimationFrame(look);
      });
    },
  };
  window.__plab = lab;
})();
"""


class Page:
    """The one tab the checks drive, and what it reported since the last look."""

    def __init__(self, cdp: Chrome, url: str, lit: dict[str, str], served_here: bool):
        self.cdp, self.url, self.lit, self.served_here = cdp, url, lit, served_here
        t = cdp.send("Target.createTarget", {"url": "about:blank"})
        self.s = cdp.send("Target.attachToTarget", {"targetId": t["targetId"], "flatten": True})["sessionId"]
        for m in ("Page.enable", "Runtime.enable", "Log.enable"):
            cdp.send(m, session=self.s)
        source = HELPER.replace("__CRASH__", json.dumps(lit["crash"])).replace("__BAND__", json.dumps(lit["band"]))
        cdp.send("Page.addScriptToEvaluateOnNewDocument", {"source": source}, session=self.s)

    def js(self, expression: str, timeout: float = 30):
        r = self.cdp.send("Runtime.evaluate", {"expression": expression, "awaitPromise": True,
                                               "returnByValue": True}, session=self.s, timeout=timeout)
        if "exceptionDetails" in r:
            d = r["exceptionDetails"]
            raise RuntimeError((d.get("exception") or {}).get("description") or d.get("text", "evaluation failed"))
        return (r.get("result") or {}).get("value")

    def call(self, fn: str, *args, timeout: float = 30):
        return self.js(f"window.__plab.{fn}({', '.join(json.dumps(a) for a in args)})", timeout)

    def load(self) -> None:
        self.cdp.send("Page.navigate", {"url": self.url}, session=self.s)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                if self.js("Boolean(window.__plab && window.__plab.ready())"):
                    self.call("settle")
                    return
            except RuntimeError:
                pass
            time.sleep(0.1)
        raise CannotRun(f"{PAGE} did not render its network select and drawing in 30 s")

    def problems(self) -> list[str]:
        """Exceptions, console errors, error-level log entries and CSP violations since the last call."""
        # These two round trips also carry in every event the page sent before them.
        csp = self.call("takeCsp")
        crash = self.call("crashed")
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
                out.append(f"log ({e.get('source')}): {e.get('text', '')[:160]}")
        out += [f"csp: {v}" for v in csp]
        if crash:
            out.append(f"error boundary: {crash}")
        return out

    def self_check(self) -> list[str]:
        """Plant one of each failure the checks look for; all three must be seen.

        Returns what else the page reported meanwhile, for the caller to fail on.
        """
        self.js("setTimeout(() => { throw new Error('protocol-lab-smoke planted exception'); }, 0);"
                "console.error('protocol-lab-smoke planted console error');"
                "new Image().src = 'https://protocol-lab-smoke.invalid/planted.png'; 0")
        need = {"exception": "planted exception", "console error": "planted console error",
                "CSP violation": "protocol-lab-smoke.invalid"}
        # Read until all three have come in, for up to PLANT_WAIT_S. A fixed 0.4 s
        # was too short on a slow CI runner: on main on 2026-11-25 the planted
        # exception had not arrived by then, and the run that was meant to show the
        # gate failing (exit 1) said it could not run (exit 2). The exception comes
        # from a timer, which waits for the page's main thread: the same day a run
        # against the deployed page, on a machine busy with other work, missed it
        # after 5 s. The loop leaves as soon as all three are in.
        found: list[str] = []
        deadline = time.monotonic() + PLANT_WAIT_S
        while True:
            time.sleep(0.2)
            found += self.problems()
            missing = [k for k, v in need.items() if not any(v in f for f in found)]
            if not missing or time.monotonic() > deadline:
                break
        if missing:
            raise CannotRun(f"a planted {', '.join(missing)} was not seen, so a real one would not be")
        return [f for f in found if not any(v in f for v in need.values())]


class Report:
    def __init__(self) -> None:
        self.passed = 0
        self.failed: list[str] = []

    def check(self, name: str, problems: list[str], detail: str = "", quiet: bool = False) -> bool:
        if problems:
            self.failed.append(name)
            print(f"  {name:<48} FAIL {detail}")
            for p in problems[:6]:
                print(f"      {p}")
            return False
        self.passed += 1
        if not quiet:
            print(f"  {name:<48} ok   {detail}")
        return True


def requests_pair(v: str | None) -> tuple[int, int] | None:
    m = re.fullmatch(r"(\d+) / (\d+)", v or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def configs(page: Page) -> list[tuple[str, str]]:
    """Every network in free play and every cited scenario, as (network, scenario or "")."""
    out = []
    for net, _ in page.call("options", "Published network"):
        page.call("choose", "Published network", net)
        page.call("settle")
        out.append((net, ""))
        out += [(net, sc) for sc, _ in page.call("options", "Cited scenario") if sc]
    return out


def go(page: Page, cfg: tuple[str, str]) -> None:
    """Load a network (and scenario) with the selects, as a reader would."""
    net, sc = cfg
    now = page.call("read")
    if now["network"] != net:
        page.call("choose", "Published network", net)
        page.call("settle")
    if sc and page.call("read")["scenario"] != sc:
        page.call("choose", "Cited scenario", sc)
    elif not sc and page.call("read")["scenario"]:
        page.call("choose", "Cited scenario", "")
    page.call("settle")


def speed(page: Page, prefix: str) -> None:
    value = next((v for v, label in page.call("options", "Simulation speed") if label.startswith(prefix)), None)
    if value is None:
        raise CannotRun(f'the speed select offers no "{prefix}..." option')
    page.call("choose", "Simulation speed", value)
    page.call("settle")


def name(cfg: tuple[str, str]) -> str:
    return f"{cfg[0]} {cfg[1] or 'free play'}"


def band_problems(page: Page, r: dict) -> list[str]:
    head = page.lit["band"]
    return [] if r["band"] and r["band"][0].startswith(head) else [f'band does not begin "{head}": {r["band"][:1]}']


# --- networks (4.4c.25) -------------------------------------------------------------------------------

def check_networks(page: Page, rep: Report, cfgs: list[tuple[str, str]]) -> None:
    print("networks: stepped, then the band, counters and supply read back")
    for cfg in cfgs:
        go(page, cfg)
        page.call("click", "Reset")
        n = 160 if cfg[1] else 22  # the SECOQC replay re-routes at ticks 60, 128 and 158
        page.call("steps", n)
        r = page.call("read")
        bad = page.problems() + band_problems(page, r)
        line2 = r["band"][1] if len(r["band"]) > 1 else ""
        if r["tick"] != n:
            bad.append(f"tick {r['tick']} after {n} Steps")
        pair = requests_pair(r["requests"])
        detail = f"{n} ticks; requests {r['requests']}"
        if (r["requests"] or "").startswith("not counted (route-only"):
            if page.lit["routeOnly"] not in r["band"][0]:
                bad.append("route-only, but the band lacks the route-only note")
            if not r["routeOnlyNote"]:
                bad.append("route-only, but the note under the drawing is missing")
            if r["keyLegend"]:
                bad.append("route-only, but the legend offers a key crossing a link")
            if "waiting for key" in line2:
                bad.append("route-only, but the band says it waits for key")
        elif cfg[1]:
            want = REPLAYS.get(cfg[1], {})
            route = r["band"][2] if len(r["band"]) > 2 else None
            if "route" in want and route != want["route"]:
                bad.append(f"ends on {route}, the source ends on {want['route']}")
            if "changes" in want and r["routeChanges"] != want["changes"]:
                bad.append(f"{r['routeChanges']} route changes, the source has {want['changes']}")
            if "failed" in want and (pair is None or pair[1] != want["failed"]):
                bad.append(f"requests {r['requests']}: the source reports none failing")
            detail += f"; {r['routeChanges']} route changes; {route}"
        elif pair is None:
            bad.append(f"free play counts no requests: {r['requests']}")
        else:
            ok, failed = pair
            if ok + failed != n:
                bad.append(f"{ok} ok + {failed} failed is not one request per tick over {n}")
            sup = supply_of(r["supply"])
            if not sup:
                bad.append(f"no supply line to compare with: {r['supply']}")
            else:
                hop, bps, key_bits, derived = sup
                per_s = bps / key_bits
                # The page rounds what it derives for display; a few per cent is rounding.
                if abs(derived - per_s) > 0.05 * per_s:
                    bad.append(f"the supply line derives {derived:g} keys/s from {bps:g} bps; "
                               f"{bps:g} / {key_bits} is {per_s:.4g}")
                detail += f"; {hop} {bps:g} bps = {per_s:.3g} keys/s"
                if per_s >= 1:
                    if failed:
                        bad.append(f"{hop} makes {per_s:.3g} keys/s, yet {failed} requests failed")
                    if "waiting for key" in line2:
                        bad.append("enough supply, but the band says it waits for key")
                else:
                    # One request a second against a hop that completes a key every
                    # 1/per_s s: only whole keys are relayed (one tick is one second).
                    want_ok = math.floor(n * per_s + 1e-9)
                    if ok != want_ok:
                        bad.append(f"{ok} delivered in {n} s; {hop}'s {bps:g} bps makes {want_ok} keys")
                    if f"waiting for key on {hop}" not in line2:
                        bad.append(f'band line "{line2}" does not name {hop} as the hop it waits on')
                    detail += f", so {want_ok} in {n} s"
        rep.check(name(cfg), bad, detail)
        sup = supply_of(r["supply"])
        if not cfg[1] and sup and sup[1] / sup[2] < 1:
            check_waiting_fraction(page, rep, cfg, sup[:3])
        page.call("click", "Reset")


def check_waiting_fraction(page: Page, rep: Report, cfg: tuple[str, str], sup: tuple[str, float, int]) -> None:
    """A slow hop: the band names it and how much of the next key it has made."""
    hop, bps, bits = sup
    page.call("click", "Reset")
    page.call("steps", 7)
    r = page.call("read")
    want = f"waiting for key on {hop} (next key {math.floor(7 * bps / bits * 100)} %)"
    bad = page.problems() + ([] if want in r["band"][1] else [f'band line "{r["band"][1]}" lacks "{want}"'])
    rep.check(f"{name(cfg)}: next key after 7 Steps", bad, want)


# --- controls (4.4c.26) -------------------------------------------------------------------------------

def wait_tick(page: Page, at_least: int, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    r = page.call("read")
    while (r["tick"] or 0) < at_least and time.monotonic() < deadline:
        time.sleep(0.1)
        r = page.call("read")
    return r


def check_controls(page: Page, rep: Report, cfgs: list[tuple[str, str]]) -> None:
    print("controls")
    keys = [c for c in cfgs if not c[1] and c[0].startswith("secoqc")] or [cfgs[0]]
    cfg = keys[0]
    go(page, cfg)
    page.call("click", "Reset")
    speed(page, "Fast")
    bad = []
    page.call("click", "Run")
    r = wait_tick(page, 3, 10)
    if r["status"] != "running" or r["tick"] < 3:
        bad.append(f"Run: status {r['status']}, tick {r['tick']} after up to 10 s")
    page.call("click", "Pause")
    page.call("settle")
    p1 = page.call("read")
    page.call("steps", 1)
    p2 = page.call("read")
    if p1["status"] != "paused" or p2["status"] != "paused" or p2["tick"] != p1["tick"] + 1:
        bad.append(f"Pause then Step: {p1['status']} t{p1['tick']} -> {p2['status']} t{p2['tick']}")
    page.call("click", "Resume")
    speed(page, "Slow")
    speed(page, "Fast")
    r = wait_tick(page, p2["tick"] + 2, 10)
    if r["status"] != "running" or r["tick"] < p2["tick"] + 2:
        bad.append(f"Resume after two speed changes: status {r['status']}, tick {r['tick']}")
    page.call("click", "Reset")
    page.call("settle")
    r = page.call("read")
    if r["status"] != "idle" or r["tick"] != 0:
        bad.append(f"Reset while running: status {r['status']}, tick {r['tick']}")
    rep.check(f"{name(cfg)}: Run, Pause, Step, Resume, speed, Reset", page.problems() + bad)

    # A failure on the first hop of the route moves the route off that hop.
    page.call("steps", 1)
    r = page.call("read")
    nodes = r["band"][2].removeprefix("Route: ").split(" > ") if len(r["band"]) > 2 else []
    links = [v for v, _ in page.call("options", "Failure target") if v.startswith("link:")]
    hop = next((v for v in links if len(nodes) > 1 and v[5:] in (f"{nodes[0]}-{nodes[1]}", f"{nodes[1]}-{nodes[0]}")), None)
    bad = []
    if not hop:
        bad.append(f"no failure target for the route's first hop ({nodes[:2]})")
    else:
        page.call("choose", "Failure target", hop)
        page.call("click", "Inject failure")
        page.call("steps", 1)
        after = page.call("read")
        moved = after["band"][2] if len(after["band"]) > 2 else ""
        if moved == r["band"][2] or f"{nodes[0]} > {nodes[1]}" in moved:
            bad.append(f"after failing {hop[5:]} the route still reads {moved}")
        if (after["routeChanges"] or "0") == "0":
            bad.append("no route change counted after the failure")
        page.call("click", "Clear failures")
        page.call("steps", 2)
    rep.check(f"{name(cfg)}: inject a failure on the route, clear it", page.problems() + bad,
              f"{hop[5:] if hop else '?'}")

    page.call("click", "Random link outage")
    page.call("steps", 3)
    page.call("click", "Clear failures")
    page.call("steps", 1)
    rep.check(f"{name(cfg)}: random link outage, cleared", page.problems() + band_problems(page, page.call("read")))

    nodes_all = [v for v, _ in page.call("options", "Demand to")]
    source = page.js('document.querySelector(\'select[aria-label="Demand from"]\')?.value ?? null')
    other = [v for v in nodes_all if v != source]
    if other:
        page.call("choose", "Demand to", other[-1])
        page.call("typeNumber", "Key requests per second", 2)
        page.call("settle")
        page.call("steps", 4)
        r = page.call("read")
        pair = requests_pair(r["requests"])
        bad = [] if pair and pair[0] + pair[1] == 8 else [f"2 requests/s over 4 ticks reads {r['requests']}"]
        rep.check(f"{name(cfg)}: another demand, 2 requests/s", page.problems() + bad, r["requests"] or "")
        page.call("typeNumber", "Key requests per second", 1)
    page.call("click", "Reset")

    for sc in [c for c in cfgs if c[1]]:
        go(page, sc)
        page.call("click", "Reset")
        page.call("steps", 1)
        events = page.call("eventButtons")
        if not events:
            continue
        before = page.call("read")["band"][2]
        bad, seen = [], [before]
        for label in events:
            page.call("click", label)
            page.call("steps", 1)
            seen.append(page.call("read")["band"][2])
        if len(seen) > 2 and (seen[1] == seen[0] or seen[-1] != seen[0]):
            bad.append(f"routes after {events}: {seen}")
        rep.check(f"{name(sc)}: its events", page.problems() + bad, " -> ".join(s.removeprefix("Route: ") for s in seen))
        page.call("click", "Reset")


# --- switches (4.4c.27) -------------------------------------------------------------------------------

def targets(cfg: tuple[str, str], cfgs: list[tuple[str, str]]) -> list[tuple[str, tuple[str, str]]]:
    """Every config one select reaches from cfg, with the select that does it."""
    nets = list(dict.fromkeys(c[0] for c in cfgs))
    out = [("Published network", (n, "")) for n in nets if n != cfg[0]]
    out += [("Cited scenario", c) for c in cfgs if c[0] == cfg[0] and c != cfg]
    return out


def parts_of(page: Page, cfg: tuple[str, str]) -> int:
    """How many parts this config's tick has, from the band during a Step."""
    go(page, cfg)
    page.call("click", "Reset")
    r = page.js("""new Promise((resolve) => {
        const t0 = performance.now(); let n = 0;
        window.__plab.click("Step");
        const look = () => {
          const m = /; now \\d+ of (\\d+), /.exec(window.__plab.band()[1] || "");
          if (m) n = Number(m[1]);
          if (n || performance.now() - t0 > 2500) resolve(n); else requestAnimationFrame(look);
        };
        requestAnimationFrame(look);
      })""")
    page.call("click", "Reset")
    return int(r or 0)


def switch_once(page: Page, rep: Report, src: tuple[str, str], part: int, drive: str,
                via: str, dst: tuple[str, str], leak_check: bool) -> bool | None:
    """True passed, False failed, None the part was never drawn in PART_TRIES ticks."""
    go(page, src)
    page.call("click", "Reset")
    page.call("settle", 2)
    wait = STEP_PLAY_WAIT_MS if drive == "Step" else RUN_PLAY_WAIT_MS
    res = {"done": False}
    for i in range(PART_TRIES):
        res = page.call("switchAt", part, drive if (drive == "Step" or i == 0) else "", via,
                        dst[1] if via == "Cited scenario" else dst[0], wait, timeout=wait / 1000 + 15)
        if res.get("done") or res.get("error"):
            break
    label = f"{drive} {name(src)} part {part} -> {name(dst)}"
    if not res.get("done") and not res.get("error"):
        print(f"  {label:<48} MISS parts drawn {res.get('seen')}")
        page.call("click", "Reset")
        return None
    time.sleep(SETTLE_S)
    page.call("settle")
    r = page.call("read")
    bad = page.problems() + band_problems(page, r)
    if res.get("error"):
        bad.append(res["error"])
    if (r["network"], r["scenario"] or "") != dst:
        bad.append(f"the selects read {r['network']} / {r['scenario']!r}, not {name(dst)}")
    if r["status"] != "idle" or r["tick"] != 0:
        bad.append(f"after the change: status {r['status']}, tick {r['tick']}")
    if leak_check and not bad:
        time.sleep(1.5)
        r2 = page.call("read")
        if r2["tick"] != 0:
            bad.append(f"{name(src)}'s run kept ticking after the change: tick {r2['tick']} 1.5 s later")
    ok = rep.check(label, bad, quiet=True)
    if r["crashed"]:
        page.load()
        speed(page, "Normal")
    return ok


def check_switches(page: Page, rep: Report, cfgs: list[tuple[str, str]]) -> None:
    speed(page, "Normal")  # the parts play at Normal; at Fast a Run lights none of them
    parts = {c: parts_of(page, c) for c in cfgs}
    if not all(parts.values()):
        rep.check("switches: every config draws its parts", [f"no parts drawn for {name(c)}" for c, n in parts.items() if not n])
        return
    print("switches: " + "; ".join(f"{name(c)} {n}" for c, n in parts.items()) + " parts")
    tally = {True: 0, False: 0, None: 0}
    for src in cfgs:
        first = True
        for via, dst in targets(src, cfgs):
            for part in range(1, parts[src] + 1):
                tally[switch_once(page, rep, src, part, "Step", via, dst, False)] += 1
            tally[switch_once(page, rep, src, parts[src], "Run", via, dst, first)] += 1
            first = False
    total = sum(tally.values())
    print(f"  {total} changes while a tick played: {tally[True]} clean, {tally[False]} failed, "
          f"{tally[None]} not tried (the part was not drawn in {PART_TRIES} ticks)")
    rep.check("switches: the part was drawn for every change", [f"{tally[None]} of {total} not tried"] if tally[None] else [])


PHASES = {"networks": check_networks, "controls": check_controls, "switches": check_switches}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dist", type=Path, default=ROOT / "services/webui-frontend/dist")
    ap.add_argument("--caddyfile", type=Path, default=ROOT / "deploy/Caddyfile")
    ap.add_argument("--policy", help="serve this policy instead of the Caddyfile's (to show the gate fails)")
    ap.add_argument("--base", help="drive this deployed origin (https://...) instead of serving --dist")
    ap.add_argument("--chrome", help="path to Chrome or Chromium (default: first one on PATH)")
    ap.add_argument("--no-sandbox", action="store_true", help="pass --no-sandbox to Chrome (CI runners)")
    ap.add_argument("--only", default=",".join(PHASES), help=f"comma-separated subset of {','.join(PHASES)}")
    a = ap.parse_args()
    sys.stdout.reconfigure(line_buffering=True)  # a CI log shows each line as it is checked
    phases = [p.strip() for p in a.only.split(",") if p.strip()]
    if not phases or any(p not in PHASES for p in phases):
        print(f"error: --only takes {','.join(PHASES)}", file=sys.stderr)
        return 2

    try:
        lit = page_literals()
        chrome = csp_smoke.find_chrome(a.chrome)
        if not chrome:
            raise CannotRun("no Chrome or Chromium found")
        policy = None
        if not a.base:
            if not (a.dist.resolve() / "index.html").is_file():
                raise CannotRun(f"no build at {a.dist} (run `npx vite build` in services/webui-frontend)")
            policy = a.policy or csp_smoke.enforced_policy(a.caddyfile)
            if not policy:
                raise CannotRun(f"{a.caddyfile} has no single enforced Content-Security-Policy line")
        version = subprocess.run([chrome, "--version"], capture_output=True, text=True).stdout.strip()
    except CannotRun as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    rep = Report()
    server = None
    with tempfile.TemporaryDirectory(prefix="protocol-lab-smoke-") as tmp:
        cdp = Chrome(chrome, Path(tmp) / "profile", a.no_sandbox)  # before the server's thread
        try:
            if a.base:
                base = a.base.rstrip("/")
            else:
                server = http.server.ThreadingHTTPServer(
                    ("127.0.0.1", 0), functools.partial(csp_smoke.Handler, policy=policy, dist=a.dist.resolve()))
                threading.Thread(target=server.serve_forever, daemon=True).start()
                base = f"http://127.0.0.1:{server.server_address[1]}"
            where = "the deployed page" if a.base else f"policy {'from --policy' if a.policy else 'from Caddyfile'}"
            print(f"{version}; {PAGE}; {where}")
            page = Page(cdp, base + PAGE, lit, served_here=not a.base)
            page.load()
            loaded = page.problems()
            loaded += page.self_check()
            print("planted exception, console error and CSP violation: all seen")
            rep.check(f"{PAGE} loads and renders", loaded + band_problems(page, page.call("read")))
            cfgs = configs(page)
            page.call("choose", "Published network", cfgs[0][0])
            started = time.monotonic()
            for p in phases:
                PHASES[p](page, rep, cfgs)
            print(f"{rep.passed + len(rep.failed)} checks, {len(rep.failed)} failed, "
                  f"{time.monotonic() - started:.0f} s")
        except CannotRun as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        finally:
            cdp.close()
            if server:
                server.shutdown()
    return 1 if rep.failed else 0


if __name__ == "__main__":
    sys.exit(main())
