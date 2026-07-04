// Shared rendering of a streamed turn. The same vocabulary (message_start /
// text_delta / reasoning_delta / tool_call / tool_result / subagent / hitl /
// question / message_end) is produced by POST /v1/chat and by GET /v1/runs/{id}/events,
// so the Chat panel and the Run drawer reduce and render it through this module.
// The implementation is split into focused siblings; this file is the public
// barrel that preserves the original export signatures.

export type { NormalizedTurn } from "@/panels/chatTurnTypes";
export { normalizeEvents } from "@/panels/chatTurnNormalizer";
export { TurnExtras } from "@/panels/chatTurnExtras";
