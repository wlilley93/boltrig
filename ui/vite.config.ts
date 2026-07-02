import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

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
  plugins: [react()],
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
    rollupOptions: {
      output: {
        // Split the heavy vendor code (React + the @xyflow/react canvas) into
        // their own chunks so the initial app bundle stays small; the canvas
        // chunk only loads when a canvas-using panel (Studio / Router tree) is
        // lazy-mounted.
        manualChunks: {
          react: ["react", "react-dom"],
          reactflow: ["@xyflow/react"],
        },
      },
    },
  },
});
