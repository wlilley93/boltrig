import { useCallback, useEffect, useRef, useState } from "react";
import type { InvokeResult, VerbInfo } from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";
import {
  readRepliesFromSettings,
  resolveRegisteredVoiceId,
} from "../../characterVoice";
import { normalisationGain } from "../voiceLoudness";
import { useFamiliarBody } from "../StageBody";
import { useCharacter } from "../characters";

const MAX_AUDIO_B64_CHARS = 12_000_000;
const MAX_SPOKEN_REPLY_CHARS = 15_000;

interface ReplySpeechActivity {
  speaking: boolean;
  level: number;
}

interface ReplySpeechState {
  enabled: boolean;
  loaded: boolean;
  provider: string | null;
  readReply(replyId: string, markdown: string): Promise<void>;
  prime(): void;
  stop(): void;
}

class ReplyAudioPlayer {
  private context: AudioContext | null = null;
  private source: AudioBufferSourceNode | null = null;
  // Held so stopSource() can tear it down. A GainNode still connected to
  // `destination` is reachable from the context and is not collected, so
  // dropping the reference and only disconnecting the source would leak one
  // node per spoken reply for the lifetime of the conversation.
  private gain: GainNode | null = null;
  private generation = 0;

  constructor(private readonly onActivity: (activity: ReplySpeechActivity) => void) {}

  prime(): void {
    const context = this.ensureContext();
    if (context?.state === "suspended") void context.resume().catch(() => undefined);
  }

  async play(bytes: ArrayBuffer): Promise<void> {
    const context = this.ensureContext();
    if (!context) throw new Error("Audio playback is unavailable in this client.");
    const generation = ++this.generation;
    this.stopSource();
    if (context.state === "suspended") await context.resume();
    const buffer = await context.decodeAudioData(bytes.slice(0));
    if (generation !== this.generation) return;
    const source = context.createBufferSource();
    source.buffer = buffer;
    // ONE LOUDNESS POLICY, HERE RATHER THAN IN EACH PROVIDER. Pocket TTS,
    // ElevenLabs and Fish all arrive at different levels, and Pocket TTS alone
    // varies by more between two renders of one register than between two
    // registers. This layer is the only one that sees every voice from every
    // provider, so it is the only place a single answer can live.
    //
    // It costs nothing: decodeAudioData has already produced the whole buffer
    // above, so the gain is measured from audio we are holding anyway and
    // applied by a node that adds no latency.
    const gain = context.createGain();
    gain.gain.value = normalisationGain(buffer.getChannelData(0));
    source.connect(gain);
    gain.connect(context.destination);
    this.gain = gain;
    source.onended = () => {
      if (this.source !== source) return;
      this.source = null;
      // Natural completion never reaches stopSource(), so the gain node has to
      // be released here too or it leaks on every reply that simply finished.
      this.gain = null;
      try { gain.disconnect(); } catch { /* Best-effort graph cleanup. */ }
      this.onActivity({ speaking: false, level: 0 });
    };
    this.source = source;
    this.onActivity({ speaking: true, level: 0.6 });
    source.start();
  }

  stop(): void {
    this.generation += 1;
    this.stopSource();
    this.onActivity({ speaking: false, level: 0 });
  }

  close(): void {
    this.stop();
    const context = this.context;
    this.context = null;
    if (context && context.state !== "closed") void context.close().catch(() => undefined);
  }

  private ensureContext(): AudioContext | null {
    if (this.context) return this.context;
    if (typeof AudioContext === "undefined") return null;
    this.context = new AudioContext();
    return this.context;
  }

  private stopSource(): void {
    const source = this.source;
    const gain = this.gain;
    this.source = null;
    this.gain = null;
    if (gain) {
      try { gain.disconnect(); } catch { /* Best-effort graph cleanup. */ }
    }
    if (!source) return;
    source.onended = null;
    try { source.stop(); } catch { /* It may already have ended. */ }
    try { source.disconnect(); } catch { /* Best-effort graph cleanup. */ }
  }
}

/** Text-chat speech is opt-in and uses the caller-scoped governed verb binding. */
export function useReplySpeech({
  conversationKey,
  onActivity,
  onError,
}: {
  conversationKey: string | null;
  onActivity(activity: ReplySpeechActivity): void;
  onError(message: string): void;
}): ReplySpeechState {
  const characterId = useFamiliarBody();
  const character = useCharacter(characterId);
  const { enabled, loaded, provider, settingsRef } = useReplySpeechConfiguration();
  const spokenRef = useRef(new Set<string>());
  const onActivityRef = useRef(onActivity);
  const onErrorRef = useRef(onError);
  onActivityRef.current = onActivity;
  onErrorRef.current = onError;
  const playerRef = useRef<ReplyAudioPlayer | null>(null);
  if (!playerRef.current) {
    playerRef.current = new ReplyAudioPlayer((activity) => onActivityRef.current(activity));
  }

  useEffect(() => {
    spokenRef.current.clear();
    playerRef.current?.stop();
  }, [conversationKey]);

  useEffect(() => () => playerRef.current?.close(), []);

  const prime = useCallback(() => {
    if (enabled) playerRef.current?.prime();
  }, [enabled]);

  const stop = useCallback(() => playerRef.current?.stop(), []);

  const readReply = useCallback(async (replyId: string, markdown: string) => {
    const speech = speechText(markdown);
    if (!enabled || !provider || !speech || spokenRef.current.has(replyId)) return;
    spokenRef.current.add(replyId);
    const voice = resolveRegisteredVoiceId(
      character,
      provider,
      settingsRef.current,
    );
    if (!voice) {
      onErrorRef.current(`${character.name} has no voice configured for ${provider}.`);
      return;
    }
    try {
      const result = await client.invoke({
        noun: "voice",
        verb: "voice.speak",
        params: { text: speech, voice },
      });
      const output = successfulSpeechOutput(result);
      if (!output) {
        onErrorRef.current(replySpeechFailure(result));
        return;
      }
      await playerRef.current?.play(decodeAudio(output.audio_b64));
    } catch {
      onErrorRef.current("The reply could not be read aloud. Text chat is unaffected.");
    }
  }, [character, enabled, provider]);

  return { enabled, loaded, provider, prime, readReply, stop };
}

/** Bind completed hosted-chat turns to speech without growing ChatView. */
export function useLiveReplySpeech({
  callActive,
  conversationKey,
  live,
  onActivity,
  onError,
}: {
  callActive: boolean;
  conversationKey: string | null;
  live: { cancelled: boolean; ended: boolean; runId?: string; text: string };
  onActivity(activity: ReplySpeechActivity): void;
  onError(message: string): void;
}) {
  const speech = useReplySpeech({ conversationKey, onActivity, onError });
  useEffect(() => {
    if (!live.runId || !live.ended || live.cancelled || !live.text.trim()) return;
    void speech.readReply(live.runId, live.text);
  }, [live.cancelled, live.ended, live.runId, live.text, speech.readReply]);
  useEffect(() => {
    if (callActive) speech.stop();
  }, [callActive, speech.stop]);
  return speech.prime;
}

function useReplySpeechConfiguration() {
  const [enabled, setEnabled] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [provider, setProvider] = useState<string | null>(null);
  const settingsRef = useRef<Record<string, unknown>>({});
  useEffect(() => {
    let cancelled = false;
    if (typeof client.meSettings !== "function" || typeof client.capabilities !== "function") {
      setLoaded(true);
      return;
    }
    void Promise.all([client.meSettings(), client.capabilities()])
      .then(([account, capabilities]) => {
        if (cancelled) return;
        settingsRef.current = account.settings ?? {};
        setEnabled(readRepliesFromSettings(account.settings));
        setProvider(voiceBinding(capabilities.verbs)?.binding?.target_ref ?? null);
        setLoaded(true);
      })
      .catch(() => {
        if (cancelled) return;
        setEnabled(false);
        setProvider(null);
        setLoaded(true);
      });
    return () => { cancelled = true; };
  }, []);
  return { enabled, loaded, provider, settingsRef };
}

function voiceBinding(verbs: VerbInfo[]): VerbInfo | undefined {
  return verbs.find((verb) => (
    verb.id === "voice.speak"
    && verb.binding?.target_type === "adapter"
    && typeof verb.binding.target_ref === "string"
  ));
}

function successfulSpeechOutput(result: InvokeResult): {
  audio_b64: string;
  content_type: string;
} | null {
  if (result.status !== "ok" || !result.output || typeof result.output !== "object") return null;
  const output = result.output as Record<string, unknown>;
  const audio = output.audio_b64;
  const contentType = output.content_type;
  if (
    typeof audio !== "string"
    || audio.length === 0
    || audio.length > MAX_AUDIO_B64_CHARS
    || typeof contentType !== "string"
    || !contentType.toLowerCase().startsWith("audio/")
  ) return null;
  return { audio_b64: audio, content_type: contentType };
}

function decodeAudio(value: string): ArrayBuffer {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes.buffer;
}

function replySpeechFailure(result: InvokeResult): string {
  if (result.status === "pending_human") {
    return "Reading this reply aloud is waiting for approval.";
  }
  if ("reason" in result) return `The reply could not be read aloud: ${result.reason}`;
  return "The voice provider returned no playable audio. Text chat is unaffected.";
}

export function speechText(markdown: string): string {
  return markdown
    .replace(/```[\s\S]*?```/g, " Code omitted. ")
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/(\*\*|__)(.*?)\1/g, "$2")
    .replace(/(^|[^\w])([*_])([^*_]+)\2/g, "$1$3")
    .replace(/^\s{0,3}#{1,6}\s+/gm, "")
    .replace(/^\s{0,3}>\s?/gm, "")
    .replace(/^\s{0,3}[-*+]\s+/gm, "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, MAX_SPOKEN_REPLY_CHARS);
}
