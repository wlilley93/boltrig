export function resultMessage(value: unknown, success: string): string {
  if (!value || typeof value !== "object") return success;
  const result = value as {
    status?: string;
    reason?: string;
    hitl_request_id?: string;
  };
  if (result.status === "pending_human") {
    return `Waiting for approval in the originating chat (${result.hitl_request_id ?? "request created"}).`;
  }
  if (result.status === "denied") {
    return `Denied: ${result.reason ?? "this identity cannot make that change"}.`;
  }
  if (result.status === "error") {
    return `Not changed: ${result.reason ?? "the kernel rejected the request"}.`;
  }
  if (result.status === "unavailable") {
    return `Not changed: ${result.reason ?? "the kernel was unreachable"}.`;
  }
  return success;
}

export function parseObject(value: string, label: string): Record<string, unknown> {
  const parsed: unknown = JSON.parse(value || "{}");
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`${label} must be a JSON object.`);
  }
  return parsed as Record<string, unknown>;
}
