/**
 * Every formula this project publishes must actually typeset.
 *
 * `docs/keyrate.md` is the document that derives the golden vector
 * R = 2.555e-3 bits/pulse, and two of its equations had never rendered:
 *
 *   Eq. 11  \frac{e_0 Y_0 + e_d\left(1 - e^{-\eta\mu\right)}{Q_\mu}\;}
 *   Eq. 12  q\left\{-Q_\mu f_{\mathrm{EC}\,h_2(E_\mu) ... \right\}\;}
 *
 * In the first, `\right)` sits inside the `e^{...}` group; in the second, the
 * `f_{` subscript is never closed, so it swallows the rest of the line. GitHub
 * showed both as raw source. They are the QBER and the secret-key rate -- the
 * two equations the whole document exists to state.
 *
 * A brace-counting check does NOT catch either one: the braces balance, and the
 * \left/\right counts balance too. They balance across the WRONG groups, which
 * only a real parser notices. That was the first thing tried here, it returned
 * clean, and it was wrong -- so this test shells out to the same parser a
 * browser would use rather than approximating one.
 *
 * The defect class is the one that keeps recurring in this repository: a
 * plausible-looking artefact nobody executed. Prose gets proofread; LaTeX
 * silently degrades to plaintext, and a reader skimming a rendered page sees a
 * mangled line and assumes their own renderer is at fault.
 */
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import katex from "katex";
import { describe, expect, it } from "vitest";

/**
 * Repo root, from services/webui-frontend/src/lib/.
 *
 * Anchored to this file rather than to `process.cwd()`, which changes with the
 * directory vitest is invoked from, and rather than to `__dirname`, which does
 * not exist in ES modules -- it resolved only because Vite's transform happens
 * to shim it, so TypeScript was right to reject it.
 */
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "..");

const trackedMarkdown = (): string[] =>
  execFileSync("git", ["ls-files", "*.md"], { cwd: ROOT, encoding: "utf8" })
    .trim()
    .split("\n")
    .filter(Boolean);

interface Expr {
  file: string;
  line: number;
  display: boolean;
  source: string;
}

/**
 * Blank out a region while preserving newlines, so later line numbers stay true.
 */
const blank = (s: string) => s.replace(/[^\n]/g, " ");

/**
 * Pull the math out of one Markdown file.
 *
 * Fenced blocks and inline code spans are blanked first: `$QKD_PARAMS_FILE` in
 * a shell example is a variable, not an equation, and feeding it to KaTeX would
 * make this test fail on correct documentation.
 */
function extract(file: string, raw: string): Expr[] {
  const text = raw
    .replace(/```[\s\S]*?```/g, blank)
    .replace(/`[^`\n]*`/g, blank);

  const lineOf = (pos: number) => text.slice(0, pos).split("\n").length;
  const found: Expr[] = [];

  // Display math first, then blank it so the inline pass cannot re-pair its
  // delimiters into a spurious expression.
  let residue = text;
  for (const m of text.matchAll(/\$\$([\s\S]+?)\$\$/g)) {
    found.push({ file, line: lineOf(m.index!), display: true, source: m[1] });
    residue =
      residue.slice(0, m.index!) +
      blank(m[0]) +
      residue.slice(m.index! + m[0].length);
  }
  for (const m of residue.matchAll(/(?<![$\\])\$(?!\$)([^$\n]+?)(?<!\\)\$(?!\$)/g)) {
    found.push({ file, line: lineOf(m.index!), display: false, source: m[1] });
  }
  return found.sort((a, b) => a.line - b.line);
}

const ALL: Expr[] = trackedMarkdown().flatMap((f) =>
  extract(f, readFileSync(join(ROOT, f), "utf8")),
);

describe("published LaTeX renders", () => {
  it("finds formulas to check", () => {
    // Guard the guard. If the extractor ever stops matching -- a delimiter
    // convention changes, the docs move -- this file would pass by checking
    // nothing at all. The count is a floor, not a pin, so adding equations
    // never breaks it.
    expect(ALL.length).toBeGreaterThan(50);
    expect(ALL.some((e) => e.file === "docs/keyrate.md" && e.display)).toBe(true);
  });

  it.each(ALL.map((e) => [`${e.file}:${e.line}`, e] as const))("%s", (_id, e) => {
    expect(() =>
      katex.renderToString(e.source, {
        displayMode: e.display,
        throwOnError: true,
        strict: "error",
      }),
    ).not.toThrow();
  });
});

describe("the parser catches what brace-counting misses", () => {
  /**
   * Both real defects had balanced braces AND balanced \left/\right. Pinning
   * that here keeps the next person from "simplifying" this test into the
   * cheaper check that already failed to catch them once.
   */
  const REAL_DEFECTS = [
    String.raw`E_\mu \;=\; \frac{e_0 Y_0 + e_d\left(1 - e^{-\eta\mu\right)}{Q_\mu}\;}`,
    String.raw`R \;\geq\; q\left\{-Q_\mu f_{\mathrm{EC}\,h_2(E_\mu) \;+\; Q_1\left[1 - h_2(e_1)\right]\right\}\;}`,
  ];

  const balanced = (s: string) => {
    let depth = 0;
    for (let i = 0; i < s.length; i++) {
      if (s[i] === "\\") { i++; continue; }
      if (s[i] === "{") depth++;
      else if (s[i] === "}") depth--;
    }
    const lr =
      (s.match(/\\left/g) ?? []).length - (s.match(/\\right/g) ?? []).length;
    return depth === 0 && lr === 0;
  };

  it.each(REAL_DEFECTS)("counting says fine, KaTeX says broken: %s", (src) => {
    expect(balanced(src)).toBe(true);
    expect(() =>
      katex.renderToString(src, { displayMode: true, throwOnError: true, strict: "error" }),
    ).toThrow();
  });
});
