const MODEL_UNAVAILABLE_COPY: Record<string, string> = {
  catalogue_unavailable: "The live model list is unavailable.",
  default_model_unconfigured: "No default chat model is configured.",
  model_gateway_unavailable: "The model gateway is unavailable.",
  model_id_unsupported: "This model identifier is not supported.",
  model_not_advertised: "This model is not currently listed by your provider.",
  text_capability_not_advertised: "This model does not advertise text input.",
  text_not_supported: "This model does not support text input.",
  trusted_codex_unavailable: "The cloud agent runtime is unavailable.",
};

/** Keep kernel reason codes out of browser-facing labels and tooltips. */
export function modelUnavailableCopy(reason?: string | null): string {
  if (!reason) return "Choose an available model.";
  if (reason === "Model choices are unavailable.") return reason;
  return MODEL_UNAVAILABLE_COPY[reason] ?? "This model is unavailable.";
}
