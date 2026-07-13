import path from "node:path";
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

import { MAX_JS_CHUNK_BYTES, oversizedChunks } from "./config/chunkBudget";

function enforceChunkBudget(): Plugin {
  return {
    name: "boltrig-chunk-budget",
    apply: "build",
    generateBundle(_options, bundle) {
      const oversized = oversizedChunks(bundle, MAX_JS_CHUNK_BYTES);
      if (oversized.length === 0) return;
      const detail = oversized.map(({ fileName, bytes }) => `${fileName} (${bytes} bytes)`).join(", ");
      this.error(`JavaScript chunk budget exceeded (max ${MAX_JS_CHUNK_BYTES} bytes): ${detail}`);
    },
  };
}

// The dev server proxies the kernel HTTP surface so the SPA can use relative
// paths in every environment. Override the kernel location with BOLTRIG_KERNEL_URL.
const KERNEL = process.env.BOLTRIG_KERNEL_URL || "http://localhost:8000";

// One proxy table for both servers: `vite dev` and `vite preview` (the e2e
// smoke serves the built dist through preview) route the kernel surface the
// same way, so the SPA always uses relative paths.
const KERNEL_PROXY = {
  "/v1": { target: KERNEL, changeOrigin: true },
  "/healthz": { target: KERNEL, changeOrigin: true },
};

export default defineConfig({
  plugins: [react(), enforceChunkBudget()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    proxy: KERNEL_PROXY,
  },
  preview: {
    port: 4173,
    strictPort: true,
    proxy: KERNEL_PROXY,
  },
  build: {
    // Vite's warning and the hard Rollup gate above use the same decimal limit.
    chunkSizeWarningLimit: MAX_JS_CHUNK_BYTES / 1000,
    rollupOptions: {
      output: {
        // Keep the heavy @xyflow/react canvas in its own chunk. It downloads
        // only when a canvas-using panel (Studio / Router tree) is lazy-mounted.
        manualChunks: {
          reactflow: ["@xyflow/react"],
        },
      },
    },
  },
});
