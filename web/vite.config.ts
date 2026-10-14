import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: the FastAPI backend runs on 127.0.0.1:8000 and Vite proxies /api to it.
// changeOrigin stays false so the backend sees Host = the Vite dev server; the Steam
// OpenID return URL it builds then points back at the dev server, not at :8000.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: false },
    },
  },
  build: {
    outDir: "dist",
    assetsDir: "assets",
  },
});
