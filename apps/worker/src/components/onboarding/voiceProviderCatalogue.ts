import type { IntegrationCatalogueEntry } from "@wlilley93/boltrig-web-sdk";

export type VoiceCapability = "Spoken replies" | "Transcription" | "Live voice";

export interface VoiceProviderDefinition {
  id: string;
  capabilities: VoiceCapability[];
  detail: string;
  info?: string;
}

const CUSTOM_INFO = "Hosted Boltrig can use a local or private speech service only when its HTTPS address is reachable and allowed by the Boltrig server. Boltrig Desktop is the private on-device option.";

export const VOICE_PROVIDERS: readonly VoiceProviderDefinition[] = [
  {
    id: "xai-voice",
    capabilities: ["Spoken replies", "Transcription", "Live voice"],
    detail: "Speech and optional realtime calls",
    info: "The key connects speech. Live voice also requires the realtime call service to be enabled by your Boltrig host.",
  },
  {
    id: "elevenlabs-audio",
    capabilities: ["Spoken replies", "Transcription"],
    detail: "Voices and transcription",
  },
  {
    id: "deepgram-audio",
    capabilities: ["Spoken replies", "Transcription"],
    detail: "Speech and transcription",
  },
  {
    id: "openai-audio",
    capabilities: ["Spoken replies", "Transcription"],
    detail: "OpenAI speech models",
  },
  {
    id: "fish-audio",
    capabilities: ["Spoken replies"],
    detail: "Expressive spoken replies",
    info: "Fish transcription appears only when the Boltrig host has enabled Fish ASR.",
  },
  {
    id: "openai-compatible-audio",
    capabilities: ["Spoken replies", "Transcription"],
    detail: "Local or self-hosted endpoint",
    info: CUSTOM_INFO,
  },
];

export function voiceCatalogueEntries(
  entries: readonly IntegrationCatalogueEntry[],
): IntegrationCatalogueEntry[] {
  const byId = new Map(entries.map((entry) => [entry.id, entry]));
  return VOICE_PROVIDERS.flatMap((definition) => {
    const entry = byId.get(definition.id);
    return entry ? [entry] : [];
  });
}

export function voiceProviderDefinition(id: string): VoiceProviderDefinition | null {
  return VOICE_PROVIDERS.find((entry) => entry.id === id) ?? null;
}
