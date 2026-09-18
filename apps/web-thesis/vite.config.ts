import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The client is served by FastAPI under /w, so assets resolve at /w/assets/*.
// Build output lands in apps/web/w so the existing "COPY apps apps" ships it.
// Dev proxies API calls to the live/local FastAPI (default: production).
const API_TARGET = process.env.EIGEN_API || "https://www.askeigen.com";

export default defineConfig({
  base: "/w/",
  plugins: [react()],
  build: {
    outDir: "../web/w",
    emptyOutDir: true,
    sourcemap: false,
  },
  server: {
    proxy: {
      // same-origin API paths the client calls; proxied in dev
      "/thesis": { target: API_TARGET, changeOrigin: true, secure: true },
      "/theses": { target: API_TARGET, changeOrigin: true, secure: true },
      "/board": { target: API_TARGET, changeOrigin: true, secure: true },
      "/config": { target: API_TARGET, changeOrigin: true, secure: true },
    },
  },
});
