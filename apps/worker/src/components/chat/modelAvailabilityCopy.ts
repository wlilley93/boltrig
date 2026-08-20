const MODEL_UNAVAILABLE_COPY: Record<string, string> = {
  catalogue_unavailable: "The live model list is unavailable.",
  default_model_unconfigured: "No default chat model is configured.",
  model_gateway_unavailable: "Models can't be reached right now.",
  model_id_unsupported: "This model name can't be used.",
  model_not_advertised: "This model is not currently listed by your provider.",
  text_capability_not_advertised: "This model doesn't list text support.",
  text_not_supported: "This model does not support text input.",
  trusted_codex_unavailable: "The assistant is not available right now.",
};

/** Keep kernel reason codes out of browser-facing labels and tooltips. */
export function modelUnavailableCopy(reason?: string | null): string {
  if (!reason) return "Choose an available model.";
  if (reason === "Model choices are unavailable.") return reason;
  return MODEL_UNAVAILABLE_COPY[reason] ?? "This model is unavailable.";
}
