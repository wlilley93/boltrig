import type { ModelEndpointInfo } from "@wlilley93/boltrig-web-sdk";

export interface AgentModelRoutingValue {
  modelEndpoint: string;
  visionModelEndpoint: string;
  modelRoutes: Record<string, string>;
  modelRouteMode: "multimodal" | "separate";
}

export function endpointSupports(endpoint: ModelEndpointInfo, modality: string): boolean {
  return (endpoint.modalities ?? ["text"]).includes(modality);
}

export function AgentModelRouting({
  endpoints,
  onChange,
  value,
}: {
  endpoints: ModelEndpointInfo[];
  onChange(next: AgentModelRoutingValue): void;
  value: AgentModelRoutingValue;
}) {
  const selected = new Set([
    value.modelEndpoint,
    value.visionModelEndpoint,
    ...Object.values(value.modelRoutes),
  ]);
  const active = endpoints.filter((endpoint) => endpoint.is_active || selected.has(endpoint.id));
  const multimodal = active.filter((endpoint) =>
    endpointSupports(endpoint, "text") && endpointSupports(endpoint, "vision"));
  const text = active.filter((endpoint) => endpointSupports(endpoint, "text"));
  const vision = active.filter((endpoint) => endpointSupports(endpoint, "vision"));

  return (
    <fieldset className="agent-model-routing">
      <legend>Model routing</legend>
      <p className="muted small">Choose one multimodal model, or use separate text and vision models.</p>
      <label><span>Model arrangement</span><select className="field-control" value={value.modelRouteMode} onChange={(event) => onChange({ ...value, modelRouteMode: event.target.value as AgentModelRoutingValue["modelRouteMode"], visionModelEndpoint: event.target.value === "multimodal" ? "" : value.visionModelEndpoint })}><option value="multimodal">One multimodal model</option><option value="separate">Text + separate vision models</option></select></label>
      <label><span>{value.modelRouteMode === "multimodal" ? "Multimodal model" : "Text model"}</span><select className="field-control" value={value.modelEndpoint} onChange={(event) => onChange({ ...value, modelEndpoint: event.target.value })}><option value="">Main API key (default)</option>{(value.modelRouteMode === "multimodal" ? multimodal : text).map((endpoint) => <option disabled={!endpoint.is_active} value={endpoint.id} key={endpoint.id}>{endpoint.id} · {endpoint.model}{endpoint.is_active ? "" : " (retired)"}</option>)}</select></label>
      {value.modelRouteMode === "separate" && <label><span>Vision model</span><select className="field-control" value={value.visionModelEndpoint} onChange={(event) => onChange({ ...value, visionModelEndpoint: event.target.value })}><option value="">Main vision key (if configured)</option>{vision.map((endpoint) => <option disabled={!endpoint.is_active} value={endpoint.id} key={endpoint.id}>{endpoint.id} · {endpoint.model}{endpoint.is_active ? "" : " (retired)"}</option>)}</select></label>}
      {endpoints.length === 0 && <p className="muted small">No per-agent override selected. This agent will inherit the main API key, and the optional main vision key for image turns.</p>}
      {value.modelRouteMode === "multimodal" && endpoints.length > 0 && multimodal.length === 0 && <p className="notice">No per-agent endpoint advertises both modalities. The main API key remains available as the default; choose separate overrides if this agent needs explicit endpoints.</p>}
      <AgentVoiceRouting endpoints={active} onChange={onChange} value={value} />
    </fieldset>
  );
}

function AgentVoiceRouting({
  endpoints,
  onChange,
  value,
}: {
  endpoints: ModelEndpointInfo[];
  onChange(next: AgentModelRoutingValue): void;
  value: AgentModelRoutingValue;
}) {
  const voice = endpoints.filter((endpoint) =>
    VOICE_MODALITIES.some((modality) => endpointSupports(endpoint, modality)));
  return (
    <div className="agent-voice-routing">
      <span>Voice overrides</span>
      <p className="muted small">Optional route references only. Provider credentials remain in the kernel.</p>
      {VOICE_MODALITIES.map((modality) => (
        <label key={modality}>
          <span>{VOICE_LABELS[modality]}</span>
          <select
            className="field-control"
            value={value.modelRoutes[modality] ?? ""}
            onChange={(event) => onChange({
              ...value,
              modelRoutes: { ...value.modelRoutes, [modality]: event.target.value },
            })}
          >
            <option value="">Deployment default</option>
            {voice.map((endpoint) => (
              <option disabled={!endpoint.is_active || !endpointSupports(endpoint, modality)} key={`${modality}-${endpoint.id}`} value={endpoint.id}>
                {endpoint.id} · {endpoint.model}{endpoint.is_active ? "" : " (retired)"}
              </option>
            ))}
          </select>
        </label>
      ))}
    </div>
  );
}

const VOICE_MODALITIES = ["stt", "tts", "realtime"] as const;
const VOICE_LABELS: Record<(typeof VOICE_MODALITIES)[number], string> = {
  stt: "Speech to text",
  tts: "Text to speech",
  realtime: "Realtime voice",
};
