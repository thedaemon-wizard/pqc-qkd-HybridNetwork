import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
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
