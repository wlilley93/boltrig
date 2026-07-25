// Public API barrel. All exports preserve the signatures and runtime values
// of the previous monolithic `client.ts` so existing callers are unaffected.

export { ApiError } from "@/api/transport";
export { StreamIdleError, streamChat, streamRunEvents } from "@/api/sse";
export type { ChatQueuedAck } from "@/api/sse";
export { api } from "@/api/api";
