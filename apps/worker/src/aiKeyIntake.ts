import type {
  SetAiKeyRequest,
  SetAiKeyResponse,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "./client";

type SafeAiKeyRequest = Omit<SetAiKeyRequest, "api_key">;

/**
 * Starts the one-time secret intake synchronously, then clears the uncontrolled
 * DOM input before any network await can retain plaintext in the UI.
 */
export function submitWriteOnlyAiKey(
  input: HTMLInputElement,
  request: SafeAiKeyRequest,
): Promise<SetAiKeyResponse> {
  const submission = client.setAiKey({ ...request, api_key: input.value });
  input.value = "";
  return submission;
}
