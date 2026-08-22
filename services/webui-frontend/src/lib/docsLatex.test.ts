/**
 * Every formula this project publishes must survive GitHub and then typeset.
 *
 * Two separate failures, found in that order.
 *
 * FIRST: `docs/keyrate.md` -- the document that derives the golden vector
 * R = 2.555e-3 bits/pulse -- had two equations that were not valid LaTeX:
 *
 *   Eq. 11  \frac{e_0 Y_0 + e_d\left(1 - e^{-\eta\mu\right)}{Q_\mu}\;}
 *   Eq. 12  q\left\{-Q_\mu f_{\mathrm{EC}\,h_2(E_\mu) ... \right\}\;}
 *
 * `\right)` sits inside the `e^{...}` group; the `f_{` subscript is never
 * closed and swallows the rest of the line. A brace-counting check does NOT
 * catch either: braces balance, and \left/\right balance -- across the wrong
 * groups. That check was written first, returned clean, and was believed until
 * a real parser disagreed. Hence KaTeX, not an approximation of it.
 *
 * SECOND, and the reason this file checks a transformed string rather than the
 * source: fixing the LaTeX was not enough, because GITHUB DOES NOT DELIVER
 * `$...$` CONTENT VERBATIM. CommonMark backslash-escape handling runs first, so
 * every `\<punctuation>` loses its backslash on the way to MathJax:
 *
 *   \;  -> ;     spacing becomes a visible semicolon
 *   \,  -> ,     spacing becomes a visible comma
 *   \{  -> {     `\left\{` becomes `\left{`, which is a parse error
 *   \_  -> _     `\mathrm{SK\_d}` silently becomes SK with subscript d
 *   \%  -> %     starts a LaTeX comment and eats the rest of the line
 *
 * Confirmed against GitHub's own renderer via `POST /markdown`, not inferred:
 * `$$R \;\geq\; q\left\{...\right\}$$` came back as
 * `$$R ;\geq; q\left{...\right}$$`. Seventeen expressions across three files
 * were affected. So a correct-LaTeX check alone still passes documents that
 * render wrong for every reader.
 *
 * Two delimiter forms are immune, because GitHub passes their contents through
 * untouched -- verified the same way:
 *
 *   ```math    fenced block   (display)
 *   $`...`$    code-span math (inline)
 *
 * This file therefore does two things: it renders every expression, and it
 * rejects any expression written in a form GitHub would damage.
 *
 * A trap worth naming: display math now lives in ```math fences, and the
 * obvious extractor blanks fenced code before looking for math -- which would
 * skip every equation this test exists to protect while still reporting a
 * healthy count. ```math is read FIRST, before any blanking.
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

/** ASCII punctuation, the set CommonMark lets a backslash escape. */
const PUNCT = "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~";
const ESCAPED_PUNCT = new RegExp(`\\\\([${PUNCT.replace(/[\\\]^-]/g, "\\$&")}])`, "g");

type Form = "fenced" | "code-span" | "dollar-display" | "dollar-inline";

interface Expr {
  file: string;
  line: number;
  form: Form;
  display: boolean;
  source: string;
}

/** Blank a region while preserving newlines, so later line numbers stay true. */
const blank = (s: string) => s.replace(/[^\n]/g, " ");

function extract(file: string, raw: string): Expr[] {
  const found: Expr[] = [];
  const lineOf = (t: string, pos: number) => t.slice(0, pos).split("\n").length;
  let t = raw;

  const take = (re: RegExp, form: Form, display: boolean) => {
    const hits: Array<[number, string, number]> = [];
    for (const m of t.matchAll(re)) hits.push([m.index!, m[1], m[0].length]);
    for (const [pos, source, len] of hits) {
      found.push({ file, line: lineOf(t, pos), form, display, source });
      t = t.slice(0, pos) + blank(t.slice(pos, pos + len)) + t.slice(pos + len);
    }
  };

  // ```math FIRST -- before any code-fence blanking, or every display equation
  // vanishes and this test silently checks nothing.
  take(/^```math[ \t]*\n([\s\S]*?)\n```[ \t]*$/gm, "fenced", true);
  // $`...`$ before generic code spans, for the same reason.
  take(/\$`([^`\n]+?)`\$/g, "code-span", false);

  // Everything else that looks like code is not maths.
  t = t.replace(/```[\s\S]*?```/g, blank).replace(/`[^`\n]*`/g, blank);

  take(/\$\$([\s\S]+?)\$\$/g, "dollar-display", true);
  take(/(?<![$\\])\$(?!\$)([^$\n]+?)(?<!\\)\$(?!\$)/g, "dollar-inline", false);

  return found.sort((a, b) => a.line - b.line);
}

const ALL: Expr[] = trackedMarkdown().flatMap((f) =>
  extract(f, readFileSync(join(ROOT, f), "utf8")),
);

describe("published LaTeX renders", () => {
  it("finds formulas to check, in both display forms", () => {
    // Guard the guard. The ```math migration is exactly the kind of change that
    // can make an extractor stop matching while the suite still reports green.
    expect(ALL.length).toBeGreaterThan(50);
    const fenced = ALL.filter((e) => e.form === "fenced");
    expect(fenced.length).toBeGreaterThan(10);
    expect(fenced.some((e) => e.file === "docs/keyrate.md")).toBe(true);
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

describe("GitHub delivers the formula unchanged", () => {
  /**
   * `$...$` and `$$...$$` lose backslash-escaped punctuation before MathJax
   * runs. Only the fenced and code-span forms are safe, so an expression that
   * needs `\;`, `\,`, `\{` or `\_` must use one of those.
   */
  const AT_RISK = ALL.filter(
    (e) => e.form === "dollar-display" || e.form === "dollar-inline",
  );

  it("has expressions in the at-risk forms to police", () => {
    // If every formula were migrated this check would be vacuous, and a future
    // `$...$` would slip in unnoticed. Inline `$x$` with no escapes is fine and
    // common, so this should stay non-empty.
    expect(AT_RISK.length).toBeGreaterThan(0);
  });

  it.each(AT_RISK.map((e) => [`${e.file}:${e.line}`, e] as const))(
    "%s survives Markdown escaping",
    (_id, e) => {
      const delivered = e.source.replace(ESCAPED_PUNCT, "$1");
      expect(
        delivered,
        `GitHub strips the backslash from \\<punctuation> inside $...$, so this ` +
          `renders as something else entirely. Move it into a \`\`\`math fence ` +
          `(display) or $\`...\`$ (inline), which GitHub passes through verbatim.`,
      ).toBe(e.source);
    },
  );
});

describe("the parser catches what brace-counting misses", () => {
  /**
   * Both original defects had balanced braces AND balanced \left/\right.
   * Pinning that keeps the next person from "simplifying" this file into the
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
    const lr = (s.match(/\\left/g) ?? []).length - (s.match(/\\right/g) ?? []).length;
    return depth === 0 && lr === 0;
  };

  it.each(REAL_DEFECTS)("counting says fine, KaTeX says broken: %s", (src) => {
    expect(balanced(src)).toBe(true);
    expect(() =>
      katex.renderToString(src, { displayMode: true, throwOnError: true, strict: "error" }),
    ).toThrow();
  });

  it("the GLLP rate would still be wrong if written with $$", () => {
    // The second failure, pinned as a fact rather than as prose: correct LaTeX
    // is not sufficient if the delimiters let Markdown edit it first.
    const correct = String.raw`R \;\geq\; q\left\{-Q_\mu f_{\mathrm{EC}}\,h_2(E_\mu)\right\}`;
    expect(() =>
      katex.renderToString(correct, { displayMode: true, throwOnError: true, strict: "error" }),
    ).not.toThrow();

    const afterGitHub = correct.replace(ESCAPED_PUNCT, "$1");
    expect(afterGitHub).toContain(String.raw`\left{`);
    expect(() =>
      katex.renderToString(afterGitHub, { displayMode: true, throwOnError: true, strict: "error" }),
    ).toThrow();
  });
});
