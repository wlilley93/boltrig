// Settings / Appearance & Accessibility: theme, density, text size, motion and
// contrast; live preview + persist to per-user settings (SET-20, NFR-A11Y-01).
// Mechanical extraction of AppearanceA11y from SettingsPanel.tsx (Beat 5).

import { useEffect, useState } from "react";

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
import { PageIntro } from "../ux";

function AppearanceA11y() {
  const settings = useFetch(() => api.meSettings(), []);
  const [appearance, setAppearance] = useState<Appearance>(() =>
    loadAppearance(),
  );
  const [adopted, setAdopted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // When the server's settings arrive, adopt them (the server is the source of
  // truth across devices; localStorage was only the instant-on mirror).
  useEffect(() => {
    if (settings.data && !adopted) {
      const fromServer = appearanceFromSettings(settings.data.settings);
      setAppearance(fromServer);
      saveAppearanceLocal(fromServer);
      setAdopted(true);
    }
  }, [settings.data, adopted]);

  function update(patch: Partial<Appearance>) {
    const next = { ...appearance, ...patch };
    setAppearance(next);
    applyAppearance(next); // live preview before Save
  }

  async function save() {
    setBusy(true);
    setMsg(null);
    setError(null);
    try {
      const res = await api.putMeSettings({
        settings: appearanceToSettings(appearance),
      });
      if (res.status === "ok") {
        saveAppearanceLocal(appearance);
        setMsg("Appearance saved.");
      } else {
        setError(res.reason ?? "save rejected");
      }
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="form">
      <div className="form__title">Appearance & accessibility</div>
      <p className="muted">
        Changes preview immediately; Save persists them to your account (SET-20,
        NFR-A11Y-01).
      </p>
      <div className="form__grid">
        <label className="field">
          <span>theme</span>
          <select
            value={appearance.theme}
            onChange={(e) => update({ theme: e.target.value })}
          >
            <option value="system">system</option>
            <option value="dark">dark</option>
            <option value="light">light</option>
          </select>
        </label>
        <label className="field">
          <span>density</span>
          <select
            value={appearance.density}
            onChange={(e) => update({ density: e.target.value })}
          >
            <option value="comfortable">comfortable</option>
            <option value="compact">compact</option>
          </select>
        </label>
        <label className="field">
          <span>font size</span>
          <select
            value={appearance.fontScale}
            onChange={(e) => update({ fontScale: e.target.value })}
          >
            <option value="0.9">small</option>
            <option value="1">normal</option>
            <option value="1.1">large</option>
            <option value="1.25">extra large</option>
          </select>
        </label>
        <label className="field">
          <span>reduced motion</span>
          <select
            value={appearance.reducedMotion ? "yes" : "no"}
            onChange={(e) => update({ reducedMotion: e.target.value === "yes" })}
          >
            <option value="no">off</option>
            <option value="yes">on</option>
          </select>
        </label>
        <label className="field">
          <span>high contrast</span>
          <select
            value={appearance.highContrast ? "yes" : "no"}
            onChange={(e) => update({ highContrast: e.target.value === "yes" })}
          >
            <option value="no">off</option>
            <option value="yes">on</option>
          </select>
        </label>
      </div>
      <div className="form__actions">
        <button className="btn btn--primary" disabled={busy} onClick={save}>
          {busy ? "..." : "Save appearance"}
        </button>
        {msg && <span className="ok">{msg}</span>}
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
