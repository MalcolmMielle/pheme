import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server (port 5173) proxies API, auth, ActivityPub and static requests
// to the FastAPI backend (`uv run pheme`, port 8000) so that session
// cookies work same-origin from the browser's point of view.
const BACKEND = "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  build: {
    // es2020 is required: the bundle must also run on Sailfish OS's Gecko
    // WebView (future sailfish-app/ shell loads this same build).
    target: "es2020",
  },
  server: {
    port: 5173,
    proxy: {
      "/api": BACKEND,
      "/actor": BACKEND,
      "/.well-known": BACKEND,
      "/login": BACKEND,
      "/register": BACKEND,
      "/logout": BACKEND,
      "/review": BACKEND,
      "/static": BACKEND,
    },
  },
});
