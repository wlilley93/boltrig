// Settings / Account & Profile: identity (read-only, from the IdP) plus the
// caller's own display name / locale / timezone preferences (SET-10).
// Mechanical extraction of AccountProfile from SettingsPanel.tsx (Beat 5).

import { useEffect, useState } from "react";

import { api } from "../../api/client";
import { useFetch } from "../../useFetch";
import { errText } from "../shared";
import { FetchError, PageIntro } from "../ux";
import { Skeleton } from "../uxFlow";
import { scopeReadable } from "./shared";

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
      setLocale(String(s["locale"] ?? ""));
      setTimezone(String(s["timezone"] ?? ""));
      setSeeded(true);
    }
  }, [settings.data, seeded]);

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
        <label className="field">
          <span>display name</span>
          <input
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
          />
        </label>
        <div className="form__grid">
          <label className="field">
            <span>locale</span>
            <input
              value={locale}
              placeholder="en-GB"
              onChange={(e) => setLocale(e.target.value)}
            />
          </label>
          <label className="field">
            <span>timezone</span>
            <input
              value={timezone}
              placeholder="Europe/London"
              onChange={(e) => setTimezone(e.target.value)}
            />
          </label>
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
