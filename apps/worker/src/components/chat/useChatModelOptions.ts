import { useEffect, useState } from "react";
import type { ChatAttachmentLimits, ChatModelChoice } from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";

const DEFAULT_ATTACHMENT_LIMITS: ChatAttachmentLimits = {
  max_count: 8,
  max_bytes: 256 * 1_024,
  max_total_bytes: 1_024 * 1_024,
  model_readable_media_types: ["text/*"],
};

/** Load server-owned model availability and attachment limits for the composer. */
export function useChatModelOptions() {
  const [modelChoices, setModelChoices] = useState<ChatModelChoice[]>([]);
  const [defaultModelName, setDefaultModelName] = useState<string | null>(null);
  const [defaultModelSource, setDefaultModelSource] = useState<"personal" | "platform">("platform");
  const [defaultModelAvailable, setDefaultModelAvailable] = useState(false);
  const [defaultModelUnavailableReason, setDefaultModelUnavailableReason] = useState<string | null>(null);
  const [modelChoicesLoaded, setModelChoicesLoaded] = useState(false);
  const [attachmentLimits, setAttachmentLimits] = useState(DEFAULT_ATTACHMENT_LIMITS);
  const [modelChoice, setModelChoice] = useState("");

  useEffect(() => {
    void client.chatModelChoices().then((result) => {
      setModelChoices(result.choices);
      setDefaultModelName(result.default_model_name ?? null);
      setDefaultModelSource(result.default_source ?? "platform");
      setDefaultModelAvailable(result.status === "unavailable"
        ? false
        : result.default_available ?? Boolean(result.default_model_name));
      setDefaultModelUnavailableReason(result.default_unavailable_reason ?? null);
      setModelChoicesLoaded(true);
    }).catch(() => {
      setModelChoices([]);
      setDefaultModelName(null);
      setDefaultModelAvailable(false);
      setDefaultModelUnavailableReason("Model choices are unavailable.");
      setModelChoicesLoaded(true);
    });
    void client.chatConfig()
      .then((result) => setAttachmentLimits(result.attachments))
      .catch(() => undefined);
  }, []);

  return {
    attachmentLimits,
    defaultModelAvailable,
    defaultModelName,
    defaultModelSource,
    defaultModelUnavailableReason,
    modelChoice,
    modelChoices,
    modelChoicesLoaded,
    setModelChoice,
  };
}
