// Round Four settings + account & access management (Epics SET / USR). One panel
// with internal sub-tabs (useState, like StudioPanel - no router). Per-user
// sections act on the caller's own scope; the Organisation section is shown only
// to org-admins, and every gated call uses tolerateStatus so a server denial
// (403) renders as a notice rather than throwing. Personal access tokens are
// minted as a subset of the caller's grants and the secret is shown ONCE
// (SEC-34); appearance choices apply live and persist as per-user settings.

import { useEffect, useState } from "react";

import { api } from "../api/client";
import type {
  ActivityRow,
  AdminInvitation,
  DirectoryUser,
  MeNotificationItem,
  MintTokenResponse,
  PatView,
  PatchUserRequest,
  SessionView,
} from "../api/types";
import { useIdentity } from "../identity";
import { useFetch } from "../useFetch";
import {
  CodeBlock,
  GrantList,
  csvToList,
  errText,
  parseJson,
  prettyJson,
} from "./shared";
import {
  type Appearance,
  appearanceFromSettings,
  appearanceToSettings,
  applyAppearance,
  loadAppearance,
  saveAppearanceLocal,
} from "../appearance";
import { PageIntro, ROLE_VALUES } from "./ux";

const ADMIN_ROLES: ReadonlySet<string> = new Set(["org-admin"]);

// One source of truth for the role set (shared with the identity + admin selects).
const ROLE_OPTIONS: ReadonlyArray<string> = ROLE_VALUES;

const EVENT_TYPES: ReadonlyArray<string> = [
  "approval",
  "escalation",
  "work_status",
  "budget_alert",
  "error",
];

const CHANNELS: ReadonlyArray<string> = [
  "in_app",
  "email",
  "slack",
  "teams",
  "webhook",
  "pager",
];

// --- small helpers ----------------------------------------------------------

function copyText(text: string): void {
  void navigator.clipboard?.writeText(text).catch(() => undefined);
}

function downloadJson(filename: string, value: unknown): void {
  const blob = new Blob([prettyJson(value)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// A scope dict (departments / nouns / verbs visible) rendered compactly.
function scopeReadable(scope: Record<string, unknown> | undefined): string {
  if (!scope || Object.keys(scope).length === 0) return "none";
  return Object.entries(scope)
    .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join("/") : String(v)}`)
    .join("; ");
}

function CopyRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="copy-row">
      <span className="copy-row__label muted">{label}</span>
      <code className="copy-row__value">{value}</code>
      <button
        className="btn"
        aria-label={`Copy ${label}`}
        onClick={() => copyText(value)}
      >
        Copy
      </button>
    </div>
  );
}

// --- Account & Profile ------------------------------------------------------

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
            <p className="muted">Loading...</p>
          )}
          {settings.error && (
            <p className="error">Failed to load: {settings.error}</p>
          )}
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

// --- Appearance & Accessibility ---------------------------------------------

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

// --- Notifications ----------------------------------------------------------

function NotificationsSection() {
  const prefs = useFetch(() => api.meNotifications(), []);

  const [eventType, setEventType] = useState(EVENT_TYPES[0]);
  const [channel, setChannel] = useState(CHANNELS[0]);
  const [target, setTarget] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  async function save(body: {
    id?: string;
    event_type: string;
    channel: string;
    target?: string;
    enabled?: boolean;
  }) {
    setBusy(true);
    setError(null);
    setMsg(null);
    try {
      const res = await api.putMeNotification(body);
      if (res.status === "ok") {
        setMsg(`Saved routing ${res.id ?? ""}.`);
        prefs.reload();
      } else {
        setError(res.reason ?? "save rejected");
      }
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  const list: MeNotificationItem[] = prefs.data?.prefs ?? [];

  return (
    <div className="cols">
      <div className="form">
        <div className="form__title">Add / update routing</div>
        <p className="muted">
          Where each kind of notification reaches you (SET-30). The server stores
          this against your own user scope.
        </p>
        <div className="form__grid">
          <label className="field">
            <span>event type</span>
            <select
              value={eventType}
              onChange={(e) => setEventType(e.target.value)}
            >
              {EVENT_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>channel</span>
            <select
              value={channel}
              onChange={(e) => setChannel(e.target.value)}
            >
              {CHANNELS.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>target</span>
            <input
              value={target}
              placeholder="address / channel / url"
              onChange={(e) => setTarget(e.target.value)}
            />
          </label>
          <label className="field">
            <span>enabled</span>
            <select
              value={enabled ? "yes" : "no"}
              onChange={(e) => setEnabled(e.target.value === "yes")}
            >
              <option value="yes">enabled</option>
              <option value="no">disabled</option>
            </select>
          </label>
        </div>
        <div className="form__actions">
          <button
            className="btn btn--primary"
            disabled={busy}
            onClick={() =>
              void save({
                event_type: eventType,
                channel,
                target: target.trim() || undefined,
                enabled,
              })
            }
          >
            {busy ? "..." : "Save routing"}
          </button>
          {msg && <span className="ok">{msg}</span>}
          {error && <span className="error">{error}</span>}
        </div>
      </div>

      <div className="list-card">
        <div className="list-card__head">
          <h3>My routing</h3>
          <button className="btn" onClick={() => prefs.reload()}>
            Refresh
          </button>
        </div>
        <div className="list-card__body">
          {prefs.loading && !prefs.data && <p className="muted">Loading...</p>}
          {prefs.error && (
            <p className="error">Failed to load: {prefs.error}</p>
          )}
          {!prefs.loading && list.length === 0 && (
            <p className="muted">No routing configured.</p>
          )}
          {list.map((pref) => (
            <div className="row-line" key={pref.id}>
              <div>
                <code>{pref.event_type}</code>{" "}
                <span className="muted">
                  via {pref.channel}
                  {pref.target ? ` -> ${pref.target}` : ""}
                </span>
              </div>
              <div className="kv">
                <span className={`badge ${pref.enabled ? "badge--ok" : ""}`}>
                  {pref.enabled ? "on" : "off"}
                </span>
                <button
                  className="btn"
                  disabled={busy}
                  onClick={() =>
                    void save({
                      id: pref.id,
                      event_type: pref.event_type,
                      channel: pref.channel,
                      target: pref.target ?? undefined,
                      enabled: !pref.enabled,
                    })
                  }
                >
                  {pref.enabled ? "Disable" : "Enable"}
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// --- Personal access tokens (shared list, used in two sections) -------------

function TokenList({ bump = 0 }: { bump?: number }) {
  const tokens = useFetch(() => api.meTokens(), [bump]);
  const [error, setError] = useState<string | null>(null);

  async function revoke(id: string) {
    if (
      !window.confirm(
        "Revoke this token? Any client using it stops working immediately.",
      )
    ) {
      return;
    }
    setError(null);
    try {
      const res = await api.revokeToken(id);
      if (res.status === "ok") tokens.reload();
      else setError(res.reason ?? "revoke rejected");
    } catch (err) {
      setError(errText(err));
    }
  }

  const list: PatView[] = tokens.data?.tokens ?? [];

  return (
    <div className="list-card">
      <div className="list-card__head">
        <h3>Personal access tokens</h3>
        <button className="btn" onClick={() => tokens.reload()}>
          Refresh
        </button>
      </div>
      <div className="list-card__body">
        {tokens.loading && !tokens.data && <p className="muted">Loading...</p>}
        {tokens.error && (
          <p className="error">Failed to load: {tokens.error}</p>
        )}
        {error && <p className="error">{error}</p>}
        {!tokens.loading && list.length === 0 && (
          <p className="muted">No tokens yet.</p>
        )}
        {list.map((t) => (
          <div className="row-line" key={t.id}>
            <div>
              <code>{t.name}</code>{" "}
              {t.revoked && <span className="badge badge--down">revoked</span>}
              <div className="muted">
                created {t.created_at ?? "-"} - last used{" "}
                {t.last_used_at ?? "never"} - expires {t.expires_at ?? "-"}
              </div>
              <GrantList grants={t.scope} />
            </div>
            {!t.revoked && (
              <button className="btn" onClick={() => void revoke(t.id)}>
                Revoke
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// --- Developer & Connections ------------------------------------------------

function DeveloperConnections() {
  const connections = useFetch(() => api.meConnections(), []);

  const [name, setName] = useState("");
  const [scope, setScope] = useState("");
  const [ttl, setTtl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [minted, setMinted] = useState<MintTokenResponse | null>(null);
  const [bump, setBump] = useState(0);

  async function mint() {
    if (!name.trim()) {
      setError("A token name is required.");
      return;
    }
    setBusy(true);
    setError(null);
    setMinted(null);
    try {
      const ttlDays = ttl.trim() ? Number(ttl.trim()) : undefined;
      if (ttlDays !== undefined && Number.isNaN(ttlDays)) {
        setError("ttl_days must be a number.");
        setBusy(false);
        return;
      }
      const res = await api.mintToken({
        name: name.trim(),
        scope: scope.trim() ? csvToList(scope) : undefined,
        ttl_days: ttlDays,
      });
      if (res.status === "ok") {
        setMinted(res);
        setName("");
        setScope("");
        setTtl("");
        setBump((n) => n + 1); // force the token list to reload
      } else {
        setError(res.reason ?? "mint rejected");
      }
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  const conn = connections.data;

  return (
    <div className="cols">
      <div className="stack">
        <div className="form">
          <div className="form__title">Mint a personal access token</div>
          <p className="muted">
            A token is scoped to a subset of your own grants and re-checked on
            every use, so it can never escalate (SEC-34).
          </p>
          <div className="form__grid">
            <label className="field">
              <span>name</span>
              <input value={name} onChange={(e) => setName(e.target.value)} />
            </label>
            <label className="field">
              <span>scope (comma list, optional)</span>
              <input
                value={scope}
                placeholder="ticket.read, ticket.comment"
                onChange={(e) => setScope(e.target.value)}
              />
            </label>
            <label className="field">
              <span>ttl_days (optional)</span>
              <input
                value={ttl}
                placeholder="30"
                onChange={(e) => setTtl(e.target.value)}
              />
            </label>
          </div>
          <div className="form__actions">
            <button
              className="btn btn--primary"
              disabled={busy}
              onClick={() => void mint()}
            >
              {busy ? "..." : "Mint token"}
            </button>
            {error && <span className="error">{error}</span>}
          </div>

          {minted && minted.secret && (
            <div className="notice warn secret-box">
              <p className="warn">
                <strong>Copy your token now.</strong> This is the only time the
                secret is shown - it is never stored in the clear and cannot be
                retrieved again.
              </p>
              <div className="copy-row">
                <code className="copy-row__value secret-box__value">
                  {minted.secret}
                </code>
                <button
                  className="btn btn--primary"
                  aria-label="Copy token secret"
                  onClick={() => copyText(minted.secret ?? "")}
                >
                  Copy
                </button>
              </div>
              <p className="muted">
                token <code>{minted.name}</code> ({minted.id}); expires{" "}
                {minted.expires_at ?? "-"}
              </p>
            </div>
          )}
        </div>

        <TokenList bump={bump} />
      </div>

      <div className="list-card">
        <div className="list-card__head">
          <h3>Connection details</h3>
          <button className="btn" onClick={() => connections.reload()}>
            Refresh
          </button>
        </div>
        <div className="list-card__body">
          {connections.loading && !connections.data && (
            <p className="muted">Loading...</p>
          )}
          {connections.error && (
            <p className="error">Failed to load: {connections.error}</p>
          )}
          {conn && (
            <>
              <CopyRow label="MCP endpoint" value={conn.mcp_endpoint} />
              <CopyRow label="REST base" value={conn.rest_base} />
              <CopyRow label="auth" value={conn.auth} />
              <p className="muted">Claude Code</p>
              <CopyRow label="claude mcp add" value={conn.snippets.claude_code} />
              <p className="muted">curl</p>
              <CopyRow label="curl" value={conn.snippets.curl} />
              <p className="muted">{conn.note}</p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// --- Personal agent ---------------------------------------------------------

function PersonalAgentSection() {
  const agent = useFetch(() => api.meAgent(), []);

  const [runtime, setRuntime] = useState("pi-worker");
  const [skills, setSkills] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function configure() {
    setBusy(true);
    setMsg(null);
    setError(null);
    try {
      const res = await api.configurePersonalAgent({
        runtime: runtime.trim() || "pi-worker",
        skills: csvToList(skills),
      });
      setMsg(`Saved agent ${res.id} (owner ${res.owner}).`);
      agent.reload();
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  const current = agent.data?.agent ?? null;

  return (
    <div className="cols">
      <div className="list-card">
        <div className="list-card__head">
          <h3>Current agent</h3>
          <button className="btn" onClick={() => agent.reload()}>
            Refresh
          </button>
        </div>
        <div className="list-card__body">
          {agent.loading && !agent.data && <p className="muted">Loading...</p>}
          {agent.error && (
            <p className="error">Failed to load: {agent.error}</p>
          )}
          {!agent.loading && current === null && (
            <p className="muted">No personal agent configured yet.</p>
          )}
          {current && (
            <>
              <div className="row-line">
                <span className="muted">runtime</span>
                <code>{current.runtime}</code>
              </div>
              <div className="row-line">
                <span className="muted">enabled</span>
                <span className={`badge ${current.enabled ? "badge--ok" : ""}`}>
                  {current.enabled ? "on" : "off"}
                </span>
              </div>
              <div className="row-line">
                <span className="muted">skills</span>
                <GrantList grants={current.skills} />
              </div>
            </>
          )}
          <p className="muted">
            Your agent runs on-behalf-of you and its grants are delegated and
            capped to your own, so it can never act beyond you (SEC-30). Invoke
            it from the Me tab.
          </p>
        </div>
      </div>

      <div className="form">
        <div className="form__title">Configure</div>
        <div className="form__grid">
          <label className="field">
            <span>runtime</span>
            <input
              value={runtime}
              onChange={(e) => setRuntime(e.target.value)}
            />
          </label>
          <label className="field">
            <span>skills (comma list)</span>
            <input value={skills} onChange={(e) => setSkills(e.target.value)} />
          </label>
        </div>
        <div className="form__actions">
          <button
            className="btn btn--primary"
            disabled={busy}
            onClick={() => void configure()}
          >
            {busy ? "..." : "Save agent"}
          </button>
          {msg && <span className="ok">{msg}</span>}
          {error && <span className="error">{error}</span>}
        </div>
      </div>
    </div>
  );
}

// --- Privacy & My Data ------------------------------------------------------

function PrivacyData() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<Awaited<
    ReturnType<typeof api.meExport>
  > | null>(null);

  async function load() {
    setBusy(true);
    setError(null);
    try {
      setData(await api.meExport());
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    if (
      !window.confirm("Delete this conversation? This closes it for your account.")
    ) {
      return;
    }
    setError(null);
    try {
      const res = await api.deleteMyConversation(id);
      if (res.status === "ok") void load();
      else setError(res.reason ?? "delete rejected");
    } catch (err) {
      setError(errText(err));
    }
  }

  const conversations = data?.conversations ?? [];

  return (
    <div className="cols">
      <div className="form">
        <div className="form__title">Export my data</div>
        <p className="muted">
          A copy of your own conversations, owned work items and settings
          (SET-60). Your data only - nothing from other users.
        </p>
        <div className="form__actions">
          <button
            className="btn btn--primary"
            disabled={busy}
            onClick={() => void load()}
          >
            {busy ? "..." : "Load export"}
          </button>
          {data && (
            <button
              className="btn"
              onClick={() => downloadJson("boltrig-export.json", data)}
            >
              Download JSON
            </button>
          )}
          {error && <span className="error">{error}</span>}
        </div>
        {data && <CodeBlock value={data} />}
      </div>

      <div className="list-card">
        <div className="list-card__head">
          <h3>My conversations</h3>
          <span className="muted">{conversations.length}</span>
        </div>
        <div className="list-card__body">
          {!data && (
            <p className="muted">Load the export to list your conversations.</p>
          )}
          {data && conversations.length === 0 && (
            <p className="muted">No conversations.</p>
          )}
          {conversations.map((c) => (
            <div className="row-line" key={c.id}>
              <div>
                <span>{c.title || "(untitled)"}</span>
                <div className="muted">
                  <code>{c.id}</code> - {c.status}
                </div>
              </div>
              <button className="btn" onClick={() => void remove(c.id)}>
                Delete
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// --- Security & Sessions ----------------------------------------------------

function SessionsList() {
  const sessions = useFetch(() => api.meSessions(), []);
  const [error, setError] = useState<string | null>(null);

  async function revoke(id: string) {
    if (!window.confirm("Revoke this session?")) return;
    setError(null);
    try {
      const res = await api.revokeSession(id);
      if (res.status === "ok") sessions.reload();
      else setError(res.reason ?? "revoke rejected");
    } catch (err) {
      setError(errText(err));
    }
  }

  const list: SessionView[] = sessions.data?.sessions ?? [];

  return (
    <div className="list-card">
      <div className="list-card__head">
        <h3>Active sessions</h3>
        <button className="btn" onClick={() => sessions.reload()}>
          Refresh
        </button>
      </div>
      <div className="list-card__body">
        {sessions.loading && !sessions.data && (
          <p className="muted">Loading...</p>
        )}
        {sessions.error && (
          <p className="error">Failed to load: {sessions.error}</p>
        )}
        {error && <p className="error">{error}</p>}
        {!sessions.loading && list.length === 0 && (
          <p className="muted">No sessions.</p>
        )}
        {list.map((s) => (
          <div className="row-line" key={s.id}>
            <div>
              <code>{s.client ?? "client"}</code>{" "}
              {s.revoked && <span className="badge badge--down">revoked</span>}
              <div className="muted">
                created {s.created_at ?? "-"} - last seen{" "}
                {s.last_seen_at ?? "-"}
              </div>
            </div>
            {!s.revoked && (
              <button className="btn" onClick={() => void revoke(s.id)}>
                Revoke
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function ActivityList() {
  const activity = useFetch(() => api.meActivity(), []);
  const rows: ActivityRow[] = activity.data?.results ?? [];

  return (
    <div className="form">
      <div className="form__title">My activity</div>
      <p className="muted">
        Your own recent actions, filtered to you (SET-72).
      </p>
      {activity.loading && !activity.data && <p className="muted">Loading...</p>}
      {activity.error && (
        <p className="error">Failed to load: {activity.error}</p>
      )}
      {!activity.loading && rows.length === 0 && (
        <p className="muted">No recent activity.</p>
      )}
      {rows.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>seq</th>
                <th>ts</th>
                <th>verb</th>
                <th>status</th>
                <th>run_id</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.seq}>
                  <td>{r.seq}</td>
                  <td>{r.ts ?? "-"}</td>
                  <td>
                    <code>{r.verb}</code>
                  </td>
                  <td>{r.status}</td>
                  <td>
                    <code>{r.run_id ?? "-"}</code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function SecuritySessions() {
  return (
    <div className="stack">
      <p className="notice">
        Boltrig stores no passwords and runs no MFA of its own - sign-in, MFA and
        password resets are managed entirely by your identity provider (SET-71).
        Tokens and sessions below are your standing credentials here; revoke any
        you do not recognise.
      </p>
      <div className="cols">
        <SessionsList />
        <TokenList />
      </div>
      <ActivityList />
    </div>
  );
}

// --- Organisation & Administration (org-admin only) -------------------------

function UserRow({
  user,
  onChanged,
}: {
  user: DirectoryUser;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [scopeText, setScopeText] = useState(() =>
    prettyJson(user.scope ?? {}),
  );

  async function patch(body: PatchUserRequest) {
    setBusy(true);
    setError(null);
    try {
      const res = await api.patchUser(user.id, body);
      if (res.status === "ok") onChanged();
      else setError(res.reason ?? "update rejected");
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  function saveScope() {
    let scope: Record<string, unknown>;
    try {
      scope = parseJson<Record<string, unknown>>(scopeText, {});
    } catch (err) {
      setError(`scope: ${errText(err)}`);
      return;
    }
    void patch({ scope });
  }

  const deactivated = user.status === "deactivated";

  return (
    <div className="dir-row">
      <div className="row-line dir-row__top">
        <div>
          <code>{user.email ?? user.id}</code>{" "}
          <span className="muted">{user.display_name ?? ""}</span>
          <div className="muted">
            {user.source ?? "idp"}
            {user.source_group ? ` / ${user.source_group}` : ""} - scope:{" "}
            {scopeReadable(user.scope)}
          </div>
          {error && <div className="error">{error}</div>}
        </div>
        <div className="kv">
          <label className="field">
            <span>role</span>
            <select
              value={user.role}
              disabled={busy}
              aria-label={`Role for ${user.email ?? user.id}`}
              onChange={(e) => void patch({ role: e.target.value })}
            >
              {ROLE_OPTIONS.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </label>
          <span
            className={`badge ${deactivated ? "badge--down" : "badge--ok"}`}
          >
            {user.status}
          </span>
          <button
            className="btn"
            disabled={busy}
            onClick={() =>
              void patch({ status: deactivated ? "active" : "deactivated" })
            }
          >
            {deactivated ? "Activate" : "Deactivate"}
          </button>
        </div>
      </div>
      <details className="dir-row__scope">
        <summary>Edit scope</summary>
        <label className="field">
          <span>scope (JSON: departments / nouns / verbs visible)</span>
          <textarea
            className="code"
            value={scopeText}
            onChange={(e) => setScopeText(e.target.value)}
          />
        </label>
        <button className="btn" disabled={busy} onClick={saveScope}>
          {busy ? "..." : "Save scope"}
        </button>
      </details>
    </div>
  );
}

function OrganisationSection() {
  const users = useFetch(() => api.adminUsers(), []);
  const invites = useFetch(() => api.adminInvitations(), []);

  const [email, setEmail] = useState("");
  const [role, setRole] = useState("agent");
  const [ttl, setTtl] = useState("14");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  async function createInvite() {
    if (!email.trim()) {
      setError("An email is required.");
      return;
    }
    setBusy(true);
    setError(null);
    setMsg(null);
    try {
      const ttlDays = ttl.trim() ? Number(ttl.trim()) : undefined;
      if (ttlDays !== undefined && Number.isNaN(ttlDays)) {
        setError("ttl_days must be a number.");
        setBusy(false);
        return;
      }
      const res = await api.createInvitation({
        email: email.trim(),
        role,
        ttl_days: ttlDays,
      });
      if (res.status === "ok") {
        setMsg(`Invited ${res.email ?? email}.`);
        setEmail("");
        invites.reload();
      } else {
        setError(res.reason ?? "invite rejected");
      }
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  async function revokeInvite(id: string) {
    if (!window.confirm("Revoke this invitation?")) return;
    setError(null);
    try {
      const res = await api.revokeInvitation(id);
      if (res.status === "ok") invites.reload();
      else setError(res.reason ?? "revoke rejected");
    } catch (err) {
      setError(errText(err));
    }
  }

  // The server returns {status:"denied", reason} (no users/invitations key) when
  // the caller is not an org-admin.
  const usersDenied =
    users.data && users.data.users === undefined
      ? users.data.reason ?? "organisation administration not permitted"
      : null;
  const userList = users.data?.users ?? [];

  const invitesDenied =
    invites.data && invites.data.invitations === undefined
      ? invites.data.reason ?? "organisation administration not permitted"
      : null;
  const inviteList = invites.data?.invitations ?? [];

  return (
    <div className="stack">
      <p className="notice">
        Manage who is in the organisation and what they may do. Deeper
        organisation configuration (privacy, network, models, HITL) lives under
        the Admin tab. Deactivating a user revokes their access immediately
        (US-USR-03).
      </p>

      <div className="list-card">
        <div className="list-card__head">
          <h3>User directory</h3>
          <button className="btn" onClick={() => users.reload()}>
            Refresh
          </button>
        </div>
        <div className="list-card__body">
          {users.loading && !users.data && <p className="muted">Loading...</p>}
          {users.error && (
            <p className="error">Failed to load: {users.error}</p>
          )}
          {usersDenied && (
            <p className="notice warn">denied: {usersDenied}</p>
          )}
          {!usersDenied && !users.loading && userList.length === 0 && (
            <p className="muted">No users.</p>
          )}
          {userList.map((u) => (
            <UserRow key={u.id} user={u} onChanged={() => users.reload()} />
          ))}
        </div>
      </div>

      <div className="cols">
        <div className="form">
          <div className="form__title">Invite a user</div>
          <p className="muted">
            An invitation pre-stages a role for an SSO identity. It creates no
            password and grants nothing until the invitee signs in through your
            IdP (SEC-35).
          </p>
          <div className="form__grid">
            <label className="field">
              <span>email</span>
              <input
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </label>
            <label className="field">
              <span>role</span>
              <select value={role} onChange={(e) => setRole(e.target.value)}>
                {ROLE_OPTIONS.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>ttl_days</span>
              <input value={ttl} onChange={(e) => setTtl(e.target.value)} />
            </label>
          </div>
          <div className="form__actions">
            <button
              className="btn btn--primary"
              disabled={busy}
              onClick={() => void createInvite()}
            >
              {busy ? "..." : "Send invitation"}
            </button>
            {msg && <span className="ok">{msg}</span>}
            {error && <span className="error">{error}</span>}
          </div>
        </div>

        <div className="list-card">
          <div className="list-card__head">
            <h3>Invitations</h3>
            <button className="btn" onClick={() => invites.reload()}>
              Refresh
            </button>
          </div>
          <div className="list-card__body">
            {invites.loading && !invites.data && (
              <p className="muted">Loading...</p>
            )}
            {invites.error && (
              <p className="error">Failed to load: {invites.error}</p>
            )}
            {invitesDenied && (
              <p className="notice warn">denied: {invitesDenied}</p>
            )}
            {!invitesDenied && !invites.loading && inviteList.length === 0 && (
              <p className="muted">No invitations.</p>
            )}
            {inviteList.map((inv: AdminInvitation) => (
              <div className="row-line" key={inv.id}>
                <div>
                  <code>{inv.email}</code>{" "}
                  <span className="muted">as {inv.intended_role}</span>
                  <div className="muted">
                    {inv.status} - invited by {inv.invited_by} - expires{" "}
                    {inv.expires_at ?? "-"}
                  </div>
                </div>
                {inv.status === "pending" && (
                  <button
                    className="btn"
                    onClick={() => void revokeInvite(inv.id)}
                  >
                    Revoke
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// --- the panel --------------------------------------------------------------

type SettingsTab =
  | "account"
  | "appearance"
  | "notifications"
  | "developer"
  | "agent"
  | "privacy"
  | "security"
  | "organisation";

interface SettingsTabDef {
  id: SettingsTab;
  label: string;
  gate?: (role: string) => boolean;
}

const SETTINGS_TABS: ReadonlyArray<SettingsTabDef> = [
  { id: "account", label: "Account & Profile" },
  { id: "appearance", label: "Appearance & Accessibility" },
  { id: "notifications", label: "Notifications" },
  { id: "developer", label: "Developer & Connections" },
  { id: "agent", label: "Personal Agent" },
  { id: "privacy", label: "Privacy & My Data" },
  { id: "security", label: "Security & Sessions" },
  {
    id: "organisation",
    label: "Organisation",
    gate: (role) => ADMIN_ROLES.has(role),
  },
];

export function SettingsPanel() {
  const identity = useIdentity();
  const [sub, setSub] = useState<SettingsTab>("account");

  const visible = SETTINGS_TABS.filter((t) => !t.gate || t.gate(identity.role));
  const active: SettingsTab = visible.some((t) => t.id === sub)
    ? sub
    : "account";

  return (
    <section className="panel">
      <PageIntro
        title="Settings"
        lead="Your account, security, and how Boltrig looks and reaches you."
        how="Org-admins also manage the directory and invitations here. Each section explains itself as you go."
      />

      <nav className="subtabs" aria-label="Settings sections">
        {visible.map((t) => (
          <button
            key={t.id}
            className={`subtab ${active === t.id ? "subtab--active" : ""}`}
            aria-current={active === t.id ? "page" : undefined}
            onClick={() => setSub(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {active === "account" && <AccountProfile />}
      {active === "appearance" && <AppearanceA11y />}
      {active === "notifications" && <NotificationsSection />}
      {active === "developer" && <DeveloperConnections />}
      {active === "agent" && <PersonalAgentSection />}
      {active === "privacy" && <PrivacyData />}
      {active === "security" && <SecuritySessions />}
      {active === "organisation" && <OrganisationSection />}
    </section>
  );
}
