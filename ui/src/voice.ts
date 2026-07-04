// Browser-native voice for the chat surface (v1). Two independent capabilities,
// both running entirely in the browser with no key and no server call:
//
//   - dictation (speech to text) via the Web Speech API's SpeechRecognition
//     (window.SpeechRecognition / window.webkitSpeechRecognition). It transcribes
//     microphone audio into the composer for the user to review before sending.
//   - read aloud (text to speech) via window.speechSynthesis. It speaks an
//     assistant reply on demand or, when the opt-in preference is on, when a
//     completed turn settles.
//
// Both are feature-detected and degrade gracefully: when the browser lacks the
// API the controls are hidden / inert and nothing throws. TypeScript's DOM lib
// ships SpeechSynthesis* but NOT SpeechRecognition, so we declare a minimal
// local shape for it here rather than pull in an @types dependency.

import { useCallback, useEffect, useRef, useState } from "react";

// --- minimal SpeechRecognition typings (absent from lib.dom) ----------------

interface SpeechRecognitionAlternativeLike {
  readonly transcript: string;
}
interface SpeechRecognitionResultLike {
  readonly isFinal: boolean;
  readonly length: number;
  [index: number]: SpeechRecognitionAlternativeLike;
}
interface SpeechRecognitionResultListLike {
  readonly length: number;
  [index: number]: SpeechRecognitionResultLike;
}
interface SpeechRecognitionEventLike {
  readonly resultIndex: number;
  readonly results: SpeechRecognitionResultListLike;
}
interface SpeechRecognitionErrorEventLike {
  readonly error: string;
  readonly message?: string;
}
interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  onresult: ((ev: SpeechRecognitionEventLike) => void) | null;
  onerror: ((ev: SpeechRecognitionErrorEventLike) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}
type SpeechRecognitionCtor = new () => SpeechRecognitionLike;

function recognitionCtor(): SpeechRecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: SpeechRecognitionCtor;
    webkitSpeechRecognition?: SpeechRecognitionCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function dictationSupported(): boolean {
  return recognitionCtor() !== null;
}

export function readAloudSupported(): boolean {
  return (
    typeof window !== "undefined" &&
    "speechSynthesis" in window &&
    typeof window.SpeechSynthesisUtterance !== "undefined"
  );
}

// A friendly, faithful reason for a recognition error (never a raw code, never
// a thrown exception the user cannot act on).
function dictationErrorText(code: string): string {
  switch (code) {
    case "not-allowed":
    case "service-not-allowed":
      return "Microphone access is blocked. Allow it in your browser to dictate.";
    case "no-speech":
      return "No speech detected - try again.";
    case "audio-capture":
      return "No microphone was found.";
    case "network":
      return "The speech service could not be reached.";
    case "aborted":
      return "";
    default:
      return "Dictation stopped unexpectedly.";
  }
}

// --- read-aloud preference (localStorage, matching appearance.ts) -----------

const READ_ALOUD_KEY = "boltrig.chat.readAloud";

export function loadReadAloud(): boolean {
  try {
    return localStorage.getItem(READ_ALOUD_KEY) === "true";
  } catch {
    return false;
  }
}

export function saveReadAloud(on: boolean): void {
  try {
    localStorage.setItem(READ_ALOUD_KEY, on ? "true" : "false");
  } catch {
    // ignore persistence failures (private mode, quota, etc.)
  }
}

// --- useDictation: push-to-talk transcription into the composer -------------
// onChange receives the full transcript accumulated since start (final chunks
// plus the current interim), and a `done` flag on the final settle so the
// caller can drop any trailing interim. The caller owns the composer text; this
// hook only reports what was heard and never sends anything on its own.

export interface Dictation {
  supported: boolean;
  listening: boolean;
  error: string | null;
  start: () => void;
  stop: () => void;
}

// Recognition setup + onresult/onerror/onend wiring, extracted from the hook so
// useDictation stays under the function floor. Reads/writes the hook's refs and
// state setters; creates the SpeechRecognition instance and starts it.
interface StartDictationArgs {
  supported: boolean;
  recRef: { current: SpeechRecognitionLike | null };
  finalRef: { current: string };
  onChangeRef: { current: (transcript: string, done: boolean) => void };
  setError: (e: string | null) => void;
  setListening: (b: boolean) => void;
}

function startDictation(a: StartDictationArgs): void {
  if (!a.supported) return;
  const Ctor = recognitionCtor();
  if (!Ctor) return;
  // Tear down any prior instance before starting a fresh session.
  if (a.recRef.current) {
    try {
      a.recRef.current.abort();
    } catch {
      /* ignore */
    }
    a.recRef.current = null;
  }
  let rec: SpeechRecognitionLike;
  try {
    rec = new Ctor();
  } catch {
    a.setError("Dictation could not start.");
    return;
  }
  rec.lang = typeof navigator !== "undefined" ? navigator.language || "en-US" : "en-US";
  rec.continuous = true;
  rec.interimResults = true;
  rec.maxAlternatives = 1;
  a.finalRef.current = "";
  a.setError(null);

  rec.onresult = (ev) => {
    let interim = "";
    for (let i = ev.resultIndex; i < ev.results.length; i++) {
      const res = ev.results[i];
      const alt = res[0];
      if (!alt) continue;
      if (res.isFinal) a.finalRef.current += alt.transcript;
      else interim += alt.transcript;
    }
    a.onChangeRef.current((a.finalRef.current + interim).trimStart(), false);
  };
  rec.onerror = (ev) => {
    const text = dictationErrorText(ev.error);
    if (text) a.setError(text);
  };
  rec.onend = () => {
    a.setListening(false);
    a.onChangeRef.current(a.finalRef.current.trim(), true);
  };

  try {
    rec.start();
    a.recRef.current = rec;
    a.setListening(true);
  } catch {
    // start() throws if invoked while already active; surface nothing fatal.
    a.setError("Dictation could not start.");
  }
}

export function useDictation(onChange: (transcript: string, done: boolean) => void): Dictation {
  const [supported] = useState<boolean>(() => dictationSupported());
  const [listening, setListening] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const recRef = useRef<SpeechRecognitionLike | null>(null);
  const finalRef = useRef(""); // accumulated finalized text this session
  // Keep the latest onChange without re-subscribing the recognition handlers.
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  const stop = useCallback(() => {
    const rec = recRef.current;
    if (!rec) return;
    try {
      rec.stop();
    } catch {
      // already stopped
    }
  }, []);

  const start = useCallback(
    () => startDictation({ supported, recRef, finalRef, onChangeRef, setError, setListening }),
    [supported],
  );

  // Stop and release the microphone on unmount.
  useEffect(() => {
    return () => {
      const rec = recRef.current;
      if (rec) {
        try {
          rec.abort();
        } catch {
          /* ignore */
        }
        recRef.current = null;
      }
    };
  }, []);

  return { supported, listening, error, start, stop };
}

// --- useSpeech: read a reply aloud (on demand or auto) ----------------------
// speakingKey identifies which message is currently being spoken (so a per
// message speaker button can toggle to "Stop"). Only assistant text is ever
// passed in - tool callouts and heartbeats are never spoken.

export interface Speech {
  supported: boolean;
  speakingKey: string | null;
  speak: (key: string, text: string) => void;
  cancel: () => void;
}

export function useSpeech(): Speech {
  const [supported] = useState<boolean>(() => readAloudSupported());
  const [speakingKey, setSpeakingKey] = useState<string | null>(null);

  const cancel = useCallback(() => {
    if (supported) {
      try {
        window.speechSynthesis.cancel();
      } catch {
        /* ignore */
      }
    }
    setSpeakingKey(null);
  }, [supported]);

  const speak = useCallback(
    (key: string, text: string) => {
      if (!supported) return;
      const clean = (text || "").trim();
      try {
        window.speechSynthesis.cancel();
      } catch {
        /* ignore */
      }
      if (!clean) {
        setSpeakingKey(null);
        return;
      }
      let utter: SpeechSynthesisUtterance;
      try {
        utter = new SpeechSynthesisUtterance(clean);
      } catch {
        setSpeakingKey(null);
        return;
      }
      utter.onend = () => setSpeakingKey((k) => (k === key ? null : k));
      utter.onerror = () => setSpeakingKey((k) => (k === key ? null : k));
      setSpeakingKey(key);
      try {
        window.speechSynthesis.speak(utter);
      } catch {
        setSpeakingKey(null);
      }
    },
    [supported],
  );

  // Stop any in-flight utterance when the surface unmounts.
  useEffect(() => {
    return () => {
      if (supported) {
        try {
          window.speechSynthesis.cancel();
        } catch {
          /* ignore */
        }
      }
    };
  }, [supported]);

  return { supported, speakingKey, speak, cancel };
}
