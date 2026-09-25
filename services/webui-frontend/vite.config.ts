import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/**
 * The @noble/post-quantum version that is actually installed, injected as
 * `__NOBLE_PQ_VERSION__` so /pqc names the library the bundle shipped.
 *
 * It was a hand-typed literal in src/lib/sim/pqc.ts that stayed at 0.7.0 after
 * the dependency moved to 0.7.1, so the page footer and the exported run log
 * misattributed every result. Read from the installed package rather than from
 * package.json's range: the range says what is allowed, this says what was
 * bundled. Read with fs because the package's `exports` map does not expose
 * its package.json. No fallback: without node_modules there is no build.
 */
const NOBLE_PQ_VERSION: string = JSON.parse(readFileSync(
  fileURLToPath(new URL("./node_modules/@noble/post-quantum/package.json", import.meta.url)),
  "utf8")).version;

export default defineConfig({
  plugins: [react()],
  define: {
    __NOBLE_PQ_VERSION__: JSON.stringify(NOBLE_PQ_VERSION),
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      // The "/ws" dev-proxy entry was removed 2026-08-28 alongside the
      // matching nginx location: webui-backend declares no websocket
      // routes and nothing in src/ opens a socket, so this forwarded
      // upgrades to a 404 in development exactly as nginx did in
      // production. Keeping it would have made the dev server disagree
      // with the deployed one about a route that works in neither.
    },
  },
});
