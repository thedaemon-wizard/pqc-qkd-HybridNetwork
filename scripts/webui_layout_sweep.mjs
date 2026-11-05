#!/usr/bin/env node
// Walks every route of a running WebUI at four widths in headless Chrome and reports
// what a reader would trip over: sideways scroll, controls with no accessible name,
// Japanese text, page errors, and SVG text lying over other SVG text. Checklist rows
// 4.2.5, 4.2.7, 4.2.8b and 4.6.18b. Needs Node 22 (for its WebSocket) and a Chrome.
//
//   node scripts/webui_layout_sweep.mjs https://demo.example [--routes /a,/b] [--widths 320,1280]
//
// It only reads: no control is pressed, except /protocol-lab's network select, walked
// so that overlap is measured on all five networks. Exit status 1 if anything is found.
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const ROUTES = ["/", "/e2e", "/paper-flow", "/bb84", "/keyflow", "/topology", "/benchmarks", "/console",
  "/physics", "/pqc", "/verify", "/hil", "/vpn", "/protocol-lab", "/qkd-protocols"];
const WIDTHS = [320, 375, 768, 1280];
const SETTLE_MS = 2500;
const PORT = 9347;

const args = process.argv.slice(2);
const base = args[0]?.replace(/\/$/, "");
if (!base) { console.error("usage: webui_layout_sweep.mjs <base-url> [--routes a,b] [--widths 320,1280]"); process.exit(2); }
const opt = (name) => { const i = args.indexOf(name); return i < 0 ? null : args[i + 1]; };
const routes = opt("--routes")?.split(",") ?? ROUTES;
const widths = opt("--widths")?.split(",").map(Number) ?? WIDTHS;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const profile = mkdtempSync(join(tmpdir(), "webui-sweep-"));
const chrome = spawn(process.env.CHROME ?? "google-chrome", ["--headless=new", `--remote-debugging-port=${PORT}`,
  `--user-data-dir=${profile}`, "--disable-gpu", "--no-first-run", "--no-default-browser-check", "about:blank"], { stdio: "ignore" });

let ws;
for (let i = 0; i < 40 && !ws; i++) {
  await sleep(250);
  try {
    const page = (await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()).find((t) => t.type === "page");
    if (page) ws = new WebSocket(page.webSocketDebuggerUrl);
  } catch { /* Chrome is not up yet */ }
}
if (!ws) { console.error("could not reach Chrome"); chrome.kill(); process.exit(2); }
await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });

let id = 0;
const waiting = new Map();
let errors = [];
ws.onmessage = (e) => {
  const m = JSON.parse(e.data);
  if (m.id && waiting.has(m.id)) { waiting.get(m.id)(m); waiting.delete(m.id); return; }
  if (m.method === "Runtime.exceptionThrown") errors.push(m.params.exceptionDetails.text.slice(0, 120));
  if (m.method === "Runtime.consoleAPICalled" && m.params.type === "error") {
    errors.push(String(m.params.args?.[0]?.value ?? "console.error").slice(0, 120));
  }
};
const send = (method, params = {}) => new Promise((res) => { const i = ++id; waiting.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
const evaluate = async (expression) => (await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true })).result?.result?.value;

// Runs in the page. Overlap is text against text, in each SVG, as it lies on the screen.
const MEASURE = `(() => {
  const named = (el) => !!(el.getAttribute("aria-label") || el.getAttribute("title") || el.textContent.trim()
    || (el.labels && el.labels.length) || el.getAttribute("aria-labelledby"));
  const controls = [...document.querySelectorAll("main button, main select, main input, main textarea, main a[href], nav button, header button")];
  const hit = (a, b) => a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
  // On screen, so a parent's transform counts, which getBBox ignores. A text's box is its
  // line box, taller than its glyphs, so two stacked lines would always touch: the box
  // measured is the middle of it, about where the glyphs are.
  const ink = (t) => {
    const r = t.getBoundingClientRect();
    return { x: r.x, width: r.width, y: r.y + r.height * 0.24, height: r.height * 0.56 };
  };
  const overlaps = [];
  for (const svg of document.querySelectorAll("main svg:not(.main-svg)")) {
    const boxes = [...svg.querySelectorAll("text")]
      .filter((t) => t.textContent.trim() && getComputedStyle(t).visibility !== "hidden" && !t.closest('[visibility="hidden"]')
        && getComputedStyle(t).display !== "none")
      .map((t) => ({ s: t.textContent.trim().slice(0, 30), b: ink(t) }));
    for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
      if (hit(boxes[i].b, boxes[j].b)) overlaps.push(boxes[i].s + " x " + boxes[j].s);
    }
  }
  return {
    scrollWidth: document.documentElement.scrollWidth,
    unnamed: controls.filter((c) => !named(c)).length,
    controls: controls.length,
    japanese: /[\\u3040-\\u30ff\\u4e00-\\u9fff]/.test(document.body.innerText),
    chars: document.body.innerText.length,
    overlaps,
  };
})()`;

await send("Page.enable");
await send("Runtime.enable");
const findings = [];
let layouts = 0;
for (const width of widths) {
  await send("Emulation.setDeviceMetricsOverride", { width, height: width < 768 ? 812 : 900, deviceScaleFactor: 1, mobile: width < 768 });
  for (const route of routes) {
    errors = [];
    await send("Page.navigate", { url: base + route });
    await sleep(SETTLE_MS);
    const checks = [await evaluate(MEASURE)];
    if (route === "/protocol-lab") {
      for (const value of ["secoqc-vienna-2008", "tokyo-2010", "madqci-2024", "thuringia-2026"]) {
        await evaluate(`(() => { const el = document.querySelector('select[aria-label="Published network"]');
          Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set.call(el, ${JSON.stringify(value)});
          el.dispatchEvent(new Event("change", { bubbles: true })); })()`);
        await sleep(300);
        checks.push(await evaluate(MEASURE));
      }
    }
    layouts += 1;
    const found = [];
    for (const c of checks) {
      if (c.scrollWidth > width) found.push(`scrolls sideways by ${c.scrollWidth - width}px`);
      if (c.unnamed) found.push(`${c.unnamed} of ${c.controls} controls unnamed`);
      if (c.japanese) found.push("Japanese text");
      if (c.chars < 40) found.push(`only ${c.chars} characters rendered`);
      for (const o of c.overlaps) found.push(`text over text: ${o}`);
    }
    for (const e of errors) found.push(`error: ${e}`);
    const unique = [...new Set(found)];
    console.log(`${String(width).padStart(4)} ${route.padEnd(16)} ${unique.length ? unique.join("; ") : "ok"}`);
    if (unique.length) findings.push({ width, route, found: unique });
  }
}
console.log(`${layouts} layouts, ${findings.length} with findings`);
ws.close();
chrome.kill();
await sleep(300);
try { rmSync(profile, { recursive: true, force: true }); } catch { /* Chrome may still hold it */ }
process.exit(findings.length ? 1 : 0);
