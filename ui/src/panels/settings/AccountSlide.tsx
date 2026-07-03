// Settings / Account & Profile: identity (read-only, from the IdP) plus the
// caller's own display name / locale / timezone preferences (SET-10).
// Mechanical extraction of AccountProfile from SettingsPanel.tsx (Beat 5).

import { useEffect, useState } from "react";

import { api } from "../../api/client";
import { useFetch } from "../../useFetch";
import { errText } from "../shared";
import { Field, FetchError, PageIntro, Select } from "../ux";
import type { Option } from "../ux";
import { Skeleton } from "../uxFlow";
import { scopeReadable } from "./shared";

// Sensible defaults from the browser so locale / timezone are never blank
// free-text (SET-10). The Select always includes the detected value + any value
// the server already holds, so nothing the user has set is ever lost.
const BROWSER_TZ =
  Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
const BROWSER_LOCALE =
  (typeof navigator !== "undefined" && navigator.language) || "en-US";

const COMMON_TIMEZONES: ReadonlyArray<string> = [
  "UTC",
  "Europe/London",
  "Europe/Paris",
  "Europe/Berlin",
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "Asia/Kolkata",
  "Asia/Singapore",
  "Asia/Tokyo",
  "Australia/Sydney",
];

const COMMON_LOCALES: ReadonlyArray<string> = [
  "en-GB",
  "en-US",
  "fr-FR",
  "de-DE",
  "es-ES",
  "it-IT",
  "pt-BR",
  "nl-NL",
  "ja-JP",
  "zh-CN",
];

// Build Select options from a common list, guaranteeing the detected + current
// values are present and first (a stored value outside the list is never lost).
function withPreferred(
  list: ReadonlyArray<string>,
  ...preferred: string[]
): Option[] {
  const seen = new Set<string>();
  const out: Option[] = [];
  for (const v of [...preferred, ...list]) {
    if (!v || seen.has(v)) continue;
    seen.add(v);
    out.push({ value: v, label: v });
  }
  return out;
}

function AccountProfile() {
  const settings = useFetch(() => api.meSettings(), []);

  const [displayName, setDisplayName] = useState("");
  const [locale, setLocale] = useState("");
  const [timezone, setTimezone] = useState("");
  const [seeded, setSeeded] = useState(false);

  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (settings.data && !seeded) {
      const s = settings.data.settings ?? {};
      setDisplayName(
        String(s["display_name"] ?? settings.data.profile.display_name ?? ""),
      );
      // Default locale / timezone from the browser when the server holds none.
      setLocale(String(s["locale"] ?? "") || BROWSER_LOCALE);
      setTimezone(String(s["timezone"] ?? "") || BROWSER_TZ);
      setSeeded(true);
    }
  }, [settings.data, seeded]);

  const localeOptions = withPreferred(COMMON_LOCALES, BROWSER_LOCALE, locale);
  const timezoneOptions = withPreferred(COMMON_TIMEZONES, BROWSER_TZ, timezone);

  async function save() {
    setBusy(true);
    setMsg(null);
    setError(null);
    try {
      const res = await api.putMeSettings({
        settings: {
          display_name: displayName.trim(),
          locale: locale.trim(),
          timezone: timezone.trim(),
        },
      });
      if (res.status === "ok") {
        setMsg("Profile preferences saved.");
        settings.reload();
      } else {
        setError(res.reason ?? "save rejected");
      }
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  const profile = settings.data?.profile;

  return (
    <div className="cols">
      <div className="list-card">
        <div className="list-card__head">
          <h3>Identity</h3>
          <span className="muted">from your IdP</span>
        </div>
        <div className="list-card__body">
          {settings.loading && !settings.data && (
            <Skeleton variant="rows" count={6} />
          )}
          <FetchError
            error={settings.error}
            status={settings.errorStatus}
            onRetry={settings.reload}
          />
          {profile && (
            <>
              <div className="row-line">
                <span className="muted">id</span>
                <code>{profile.id}</code>
              </div>
              <div className="row-line">
                <span className="muted">email</span>
                <span>{profile.email ?? "-"}</span>
              </div>
              <div className="row-line">
                <span className="muted">role</span>
                <code className="tag">{profile.role ?? "-"}</code>
              </div>
              <div className="row-line">
                <span className="muted">status</span>
                <span
                  className={`badge ${profile.status === "deactivated" ? "badge--down" : "badge--ok"}`}
                >
                  {profile.status ?? "-"}
                </span>
              </div>
              <div className="row-line">
                <span className="muted">source IdP group</span>
                <span>{profile.source_group ?? "-"}</span>
              </div>
              <div className="row-line">
                <span className="muted">scope</span>
                <span>{scopeReadable(profile.scope)}</span>
              </div>
              <p className="muted">
                Role, scope and group are conferred by your identity provider and
                are read-only here. Change them via your IdP, or ask an org-admin.
              </p>
            </>
          )}
        </div>
      </div>

      <div className="form">
        <div className="form__title">Preferences</div>
        <p className="muted">
          A preferred display name and your locale / timezone. These are your own
          per-user settings (SET-10).
        </p>
        <Field label="Display name" hint="A preferred name shown in the app.">
          <input
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
          />
        </Field>
        <div className="form__grid">
          <Field label="Locale" hint="Defaults from your browser.">
            <Select
              value={locale}
              ariaLabel="Locale"
              onChange={setLocale}
              options={localeOptions}
            />
          </Field>
          <Field label="Timezone" hint="Defaults from your browser.">
            <Select
              value={timezone}
              ariaLabel="Timezone"
              onChange={setTimezone}
              options={timezoneOptions}
            />
          </Field>
        </div>
        <div className="form__actions">
          <button className="btn btn--primary" disabled={busy} onClick={save}>
            {busy ? "..." : "Save preferences"}
          </button>
          {msg && <span className="ok">{msg}</span>}
          {error && <span className="error">{error}</span>}
        </div>
      </div>
    </div>
  );
}

export function AccountSlide() {
  return (
    <section className="panel">
      <PageIntro title="Account & Profile" lead="Name, locale and timezone." />
      <AccountProfile />
    </section>
  );
}
