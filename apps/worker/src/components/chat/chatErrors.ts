import { BoltrigApiError } from "@wlilley93/boltrig-web-sdk";

export function reasonText(reason: unknown): string {
  if (reason instanceof BoltrigApiError) {
    if (reason.status === 401) return "Sign in to Boltrig to continue.";
    if (reason.status === 403) return "This workspace does not grant that action.";
    if (reason.status === 413) {
      return "The server rejected the attachment limits. Your task draft has been restored.";
    }
    if (reason.status === 503) return "This capability is unavailable right now.";
  }
  return reason instanceof Error ? reason.message : "Something went wrong.";
}
