import { useEffect, useState } from "react";

import { client } from "../../client";
import {
  readRepliesFromSettings,
  readRepliesToSettings,
} from "../../characterVoice";
import { SettingsRow, SettingsToggle } from "./rowKit";

/** Persisted opt-in for governed text-to-speech of completed chat replies. */
export function ReadRepliesSetting() {
  const [enabled, setEnabled] = useState(false);
  const [state, setState] = useState<"loading" | "ready" | "unavailable">("loading");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    let cancelled = false;
    if (typeof client.meSettings !== "function") {
      setState("unavailable");
      return;
    }
    void client.meSettings()
      .then((result) => {
        if (cancelled) return;
        setEnabled(readRepliesFromSettings(result.settings));
        setState("ready");
      })
      .catch(() => {
        if (!cancelled) setState("unavailable");
      });
    return () => { cancelled = true; };
  }, []);

  async function toggle(next: boolean) {
    if (busy || state !== "ready") return;
    const previous = enabled;
    setEnabled(next);
    setBusy(true);
    setMessage("");
    try {
      const result = await client.putMeSettings({ settings: readRepliesToSettings(next) });
      if (result.status !== "ok") {
        setEnabled(previous);
        setMessage(result.reason ?? "Read-out replies could not be saved.");
      }
    } catch {
      setEnabled(previous);
      setMessage("Read-out replies could not be saved.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <SettingsRow
        control={(
          <SettingsToggle
            disabled={busy || state !== "ready"}
            label="Read out replies"
            on={enabled}
            onToggle={(next) => void toggle(next)}
          />
        )}
        desc={state === "unavailable"
          ? "Voice settings could not be read."
          : "Speaks completed text-chat replies in your selected companion's voice."}
        title="Read out replies"
      />
      {message && <span className="settings-visually-hidden" role="status">{message}</span>}
    </>
  );
}
