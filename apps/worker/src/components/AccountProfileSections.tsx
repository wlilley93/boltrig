import { useEffect, useState } from "react";
import type {
  ActivityRow,
  MeSettingsResponse,
  PrivacyPolicyResponse,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../client";
import { Unavailable } from "./Shell";

export function ProfileSettings({
  account,
  onSaved,
}: {
  account: MeSettingsResponse;
  onSaved(): void;
}) {
  const [theme, setTheme] = useState(stringSetting(account.settings.theme));
  const [locale, setLocale] = useState(stringSetting(account.settings.locale));
  const [timezone, setTimezone] = useState(stringSetting(account.settings.timezone));
  const [message, setMessage] = useState("");

  async function save() {
    const result = await client.putMeSettings({
      settings: {
        theme: theme || "system",
        locale: locale || "en",
        timezone: timezone || "UTC",
      },
    });
    setMessage(result.status === "ok" ? "Preferences saved." : result.reason ?? result.status);
    if (result.status === "ok") {
      applyTheme(theme || "system");
      onSaved();
    }
  }

  return (
    <section className="settings-card">
      <p className="eyebrow">Profile and preferences</p>
      <h2>{account.profile.display_name || account.profile.email || account.profile.id}</h2>
      <p>{account.profile.role || "member"} · {account.profile.status || "active"}</p>
      <label>
        <span className="muted small">Theme</span>
        <select
          className="field-control"
          aria-label="Theme"
          value={theme}
          onChange={(event) => setTheme(event.target.value)}
        >
          <option value="system">System</option>
          <option value="light">Light</option>
          <option value="dark">Dark</option>
        </select>
      </label>
      <label>
        <span className="muted small">Locale</span>
        <input
          className="field-control"
          aria-label="Locale"
          value={locale}
          onChange={(event) => setLocale(event.target.value)}
          placeholder="en"
        />
      </label>
      <label>
        <span className="muted small">Timezone</span>
        <input
          className="field-control"
          aria-label="Timezone"
          value={timezone}
          onChange={(event) => setTimezone(event.target.value)}
          placeholder="UTC"
        />
      </label>
      {(account.setting_sources?.locale === "tenant_default"
        || account.setting_sources?.timezone === "tenant_default") && (
        <p className="muted small">
          Unchanged locale and timezone values come from your organisation defaults.
        </p>
      )}
      <div className="button-row">
        <button className="primary-button" onClick={() => void save()}>Save preferences</button>
      </div>
      {message && <p className="notice" role="status">{message}</p>}
    </section>
  );
}

export function ActivityAndExport() {
  const [activity, setActivity] = useState<ActivityRow[]>([]);
  const [offset, setOffset] = useState(0);
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  async function loadActivity(pageOffset: number) {
    setLoading(true);
    try {
      const result = await client.meActivity({ limit: 8, offset: pageOffset });
      setActivity(result.results);
      setOffset(result.offset ?? pageOffset);
      setNextOffset(result.next_offset ?? null);
      setMessage("");
    } catch {
      setMessage("Account activity is unavailable.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void loadActivity(0); }, []);

  async function exportData() {
    setMessage("Preparing your account summary…");
    try {
      const payload = await client.meExport();
      downloadJson(payload, `boltrig-account-summary-${payload.user}.json`);
      setMessage("Account summary prepared on this device.");
    } catch {
      setMessage("Your account summary could not be prepared.");
    }
  }

  return (
    <section className="settings-card">
      <p className="eyebrow">Activity and export</p>
      <h2>Your recent account activity</h2>
      <div className="data-list" aria-label="Account activity">
        {activity.map((row) => (
          <div className="data-row static" key={row.seq}>
            <span className={`activity-dot ${row.status}`} />
            <span className="data-row-copy">
              <strong>{row.verb}</strong>
              <small>{formatDate(row.ts)}{row.run_id ? ` · ${row.run_id}` : ""}</small>
            </span>
            <span className="row-meta">{row.status}</span>
          </div>
        ))}
        {activity.length === 0 && <p className="muted">No account activity is visible.</p>}
      </div>
      <div className="button-row" aria-label="Account activity pages">
        <button className="secondary-button" disabled={loading || offset === 0}
          onClick={() => void loadActivity(Math.max(0, offset - 8))}>Newer</button>
        <button className="secondary-button" disabled={loading || nextOffset === null}
          onClick={() => void loadActivity(nextOffset ?? offset)}>Older</button>
      </div>
      <button className="secondary-button" onClick={() => void exportData()}>
        Export account summary
      </button>
      <p className="muted small">
        Includes your conversation index, owned work-item summaries, and account settings.
        It is not a complete content or compliance export.
      </p>
      {message && <p className="notice" role="status">{message}</p>}
    </section>
  );
}

export function PrivacyPolicyEvidence() {
  const [policy, setPolicy] =
    useState<PrivacyPolicyResponse["policy"] | null>(null);
  const [unavailable, setUnavailable] = useState(false);

  useEffect(() => {
    void Promise.resolve()
      .then(() => client.privacyPolicy())
      .then((result) => {
        setPolicy(result.policy);
        setUnavailable(false);
      })
      .catch(() => {
        setPolicy(null);
        setUnavailable(true);
      });
  }, []);

  return (
    <section className="settings-card">
      <p className="eyebrow">Process-start evidence</p>
      <h2>Privacy coverage</h2>
      {policy ? (
        <>
          <p>{`Closed-conversation retention: ${
            policy.retention.days === null
              ? "not configured"
              : `${policy.retention.days} days`
          }`}</p>
          <Unavailable title="Partial enforcement only">
            Retention currently covers closed conversation messages only.
            PII redaction, configured field rules and data residency have no
            complete serving consumer. Account export is a bounded summary, not
            a compliance archive.
          </Unavailable>
        </>
      ) : (
        <Unavailable title="Privacy evidence unavailable">
          {unavailable
            ? "Effective privacy coverage could not be loaded."
            : "Loading effective privacy coverage…"}
        </Unavailable>
      )}
    </section>
  );
}

function stringSetting(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function applyTheme(theme: string) {
  try {
    localStorage.setItem("boltrig-worker-theme", theme);
    const dark = theme === "dark"
      || (theme !== "light" && matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.dataset.theme = dark ? "dark" : "light";
  } catch {
    // A hardened browser may deny storage/media queries; server preference still saved.
  }
}

function formatDate(value: string | null): string {
  if (!value) return "No timestamp";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function downloadJson(payload: unknown, filename: string) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
