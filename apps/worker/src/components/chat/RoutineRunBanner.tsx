import { useState } from "react";
import type {
  ConversationResponse,
  ConversationSummary,
} from "@wlilley93/boltrig-web-sdk";

import { navigate } from "../../routes";

export type ConversationProvenance = Pick<
  ConversationSummary,
  "origin" | "source_ref" | "source_run_id" | "companion_id"
>;

export function useConversationProvenance() {
  const [value, setValue] = useState<ConversationProvenance | null>(null);
  return {
    value,
    clear: () => setValue(null),
    load: (thread: ConversationResponse, summary: ConversationSummary) => {
      const source = thread.conversation ?? summary;
      setValue({
        origin: source.origin,
        source_ref: source.source_ref,
        source_run_id: source.source_run_id,
        companion_id: source.companion_id,
      });
    },
  };
}

export function RoutineRunBanner({ provenance }: {
  provenance: ConversationProvenance | null;
}) {
  if (provenance?.origin !== "routine") return null;
  const companion = provenance.companion_id === "jarvis" ? "Jarvis" : "Familiar";
  return <section className="routine-run-banner" aria-label="Automatic routine run">
    <span aria-hidden className="routine-run-mark" />
    <span>
      <strong>Automatic routine</strong>
      <small>{provenance.source_ref ?? "Routine"} · {companion}</small>
    </span>
  </section>;
}
