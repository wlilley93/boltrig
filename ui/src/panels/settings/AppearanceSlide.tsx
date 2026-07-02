// Settings / Appearance & Accessibility: theme, density, text size, motion and
// contrast (SET-20, NFR-A11Y-01). Controls are instant-apply with a debounced
// persist (settings-retrofit spec 1.3): a change previews and saves on its
// own; a failed persist reverts the applied appearance to the saved truth and
// surfaces the server reason.

import { useEffect, useRef, useState } from "react";

import { api } from "../../api/client";
import {
  type Appearance,
  appearanceFromSettings,
  appearanceToSettings,
  applyAppearance,
  loadAppearance,
  saveAppearanceLocal,
} from "../../appearance";
import { useFetch } from "../../useFetch";
import { errText } from "../shared";
import { FetchError, Field, InfoCallout, PageIntro, type Option } from "../ux";
import { SegmentedV2, Switch, useSavedWisp } from "../uxForm";

const PERSIST_DEBOUNCE_MS = 800;

const THEME_OPTIONS: Option[] = [
  { value: "system", label: "System" },
  { value: "dark", label: "Dark" },
  { value: "light", label: "Light" },
];

const DENSITY_OPTIONS: Option[] = [
  { value: "comfortable", label: "Comfortable" },
  { value: "compact", label: "Compact" },
];

const TEXT_SIZE_OPTIONS: Option[] = [
  { value: "0.9", label: "Small" },
  { value: "1", label: "Normal" },
  { value: "1.1", label: "Large" },
  { value: "1.25", label: "Extra large" },
];

function AppearanceA11y() {
  const settings = useFetch(() => api.meSettings(), []);
  const [appearance, setAppearance] = useState<Appearance>(() =>
    loadAppearance(),
  );
  const [adopted, setAdopted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [wisp, savedWisp] = useSavedWisp();

  // The last appearance the server accepted: the revert target on a failed
  // persist (the preview must never drift from the saved truth on error).
  const savedRef = useRef<Appearance>(loadAppearance());
  // The change awaiting its debounced persist, if any.
  const pendingRef = useRef<Appearance | null>(null);
  const timerRef = useRef<number | undefined>(undefined);
  const aliveRef = useRef(true);

  // When the server's settings arrive, adopt them (the server is the source of
  // truth across devices; localStorage was only the instant-on mirror).
  useEffect(() => {
    if (settings.data && !adopted) {
      const fromServer = appearanceFromSettings(settings.data.settings);
      setAppearance(fromServer);
      saveAppearanceLocal(fromServer);
      savedRef.current = fromServer;
      setAdopted(true);
    }
  }, [settings.data, adopted]);

  // On unmount, flush any still-debouncing change (fire and forget) so an
  // applied appearance is not silently dropped server-side by a slide move.
  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
      window.clearTimeout(timerRef.current);
      const pending = pendingRef.current;
      if (pending) {
        void api
          .putMeSettings({ settings: appearanceToSettings(pending) })
          .catch(() => undefined);
      }
    };
  }, []);

  function revert(reason: string) {
    // A newer edit is already queued: its persist will settle the truth, so
    // only surface the reason instead of yanking the preview around.
    if (pendingRef.current) {
      if (aliveRef.current) setError(reason);
      return;
    }
    const saved = savedRef.current;
    applyAppearance(saved);
    if (!aliveRef.current) return;
    setAppearance(saved);
    setError(reason);
  }

  async function persist(next: Appearance) {
    pendingRef.current = null;
    try {
      const res = await api.putMeSettings({
        settings: appearanceToSettings(next),
      });
      if (res.status === "ok") {
        savedRef.current = next;
        saveAppearanceLocal(next);
        if (aliveRef.current) savedWisp();
      } else {
        revert(res.reason ?? "save rejected");
      }
    } catch (err) {
      revert(errText(err));
    }
  }

  function update(patch: Partial<Appearance>) {
    const next = { ...appearance, ...patch };
    setAppearance(next);
    setError(null);
    applyAppearance(next); // instant apply
    pendingRef.current = next;
    window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(
      () => void persist(next),
      PERSIST_DEBOUNCE_MS,
    );
  }

  return (
    <div className="form">
      <div className="form__title">Appearance & accessibility</div>
      <InfoCallout tone="info">
        Changes apply immediately and follow you across devices.
      </InfoCallout>
      <FetchError
        error={settings.error}
        status={settings.errorStatus}
        onRetry={settings.reload}
      />
      <div className="form__grid">
        <Field label="Theme" hint="Dark is the native Boltrig look.">
          <SegmentedV2
            value={appearance.theme}
            onChange={(v) => update({ theme: v })}
            options={THEME_OPTIONS}
            ariaLabel="Theme"
          />
        </Field>
        <Field label="Density" hint="Compact tightens tables and lists.">
          <SegmentedV2
            value={appearance.density}
            onChange={(v) => update({ density: v })}
            options={DENSITY_OPTIONS}
            ariaLabel="Density"
          />
        </Field>
        <Field label="Text size">
          <SegmentedV2
            value={appearance.fontScale}
            onChange={(v) => update({ fontScale: v })}
            options={TEXT_SIZE_OPTIONS}
            ariaLabel="Text size"
          />
        </Field>
        <Switch
          checked={appearance.reducedMotion}
          onChange={(v) => update({ reducedMotion: v })}
          label="Reduced motion"
          hint="Disables slide transitions and animation."
        />
        <Switch
          checked={appearance.highContrast}
          onChange={(v) => update({ highContrast: v })}
          label="High contrast"
          hint="Stronger borders and text contrast."
        />
      </div>
      <div className="form__actions">
        {wisp}
        {error && <span className="error">{error}</span>}
      </div>
    </div>
  );
}

export function AppearanceSlide() {
  return (
    <section className="panel">
      <PageIntro
        title="Appearance & Accessibility"
        lead="Theme, density, text size, motion and contrast."
      />
      <AppearanceA11y />
    </section>
  );
}
