import { BoltrigClient } from "@wlilley93/boltrig-web-sdk";

export const client = new BoltrigClient({
  baseUrl: import.meta.env.VITE_API_BASE ?? "",
});
