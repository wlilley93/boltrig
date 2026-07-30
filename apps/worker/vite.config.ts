import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

const kernel = process.env.BOLTRIG_KERNEL_URL ?? "http://localhost:8000";

export default defineConfig({
  base: "./",
  plugins: [react()],
  resolve: {
    alias: {
      "@wlilley93/boltrig-web-sdk": path.resolve(__dirname, "../../sdks/web/src/index.ts"),
    },
  },
  server: {
    port: 1420,
    strictPort: true,
    proxy: {
      "/v1": { target: kernel, changeOrigin: true },
      "/healthz": { target: kernel, changeOrigin: true },
      "/readyz": { target: kernel, changeOrigin: true },
    },
  },
  preview: {
    port: 4180,
    strictPort: true,
    proxy: {
      "/v1": { target: kernel, changeOrigin: true },
      "/healthz": { target: kernel, changeOrigin: true },
      "/readyz": { target: kernel, changeOrigin: true },
    },
  },
  clearScreen: false,
  envPrefix: ["VITE_", "TAURI_"],
});
