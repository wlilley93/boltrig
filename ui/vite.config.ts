import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dev server proxies the kernel HTTP surface so the SPA can use relative
// paths in every environment. Override the kernel location with BOLTRIG_KERNEL_URL.
const KERNEL = process.env.BOLTRIG_KERNEL_URL || "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/v1": { target: KERNEL, changeOrigin: true },
      "/healthz": { target: KERNEL, changeOrigin: true },
    },
  },
});
