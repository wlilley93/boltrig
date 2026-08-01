import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

const kernel = process.env.BOLTRIG_KERNEL_URL ?? "http://localhost:8000";
// nginx.conf proxies /voice/ to the channel gateway with the prefix stripped.
// Dev and preview mirror it, so the kernel's relative websocket_url upgrades
// here the same way it does in the shipped image.
const gateway = process.env.BOLTRIG_CHANNEL_GATEWAY_URL ?? "http://localhost:8091";
const voice = {
  target: gateway,
  changeOrigin: true,
  ws: true,
  rewrite: (path: string) => path.replace(/^\/voice/, ""),
};

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
      "/voice": voice,
    },
  },
  preview: {
    port: 4180,
    strictPort: true,
    proxy: {
      "/v1": { target: kernel, changeOrigin: true },
      "/healthz": { target: kernel, changeOrigin: true },
      "/readyz": { target: kernel, changeOrigin: true },
      "/voice": voice,
    },
  },
  clearScreen: false,
  envPrefix: ["VITE_", "TAURI_"],
});
