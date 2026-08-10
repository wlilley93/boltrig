import { useEffect, useState } from "react";
import type {
  KnowledgeProvider,
  MeSettingsResponse,
  OrganisationView,
  WorkspaceView,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";
import { isDesktop } from "../../desktop";
import {
  DeveloperDetailsRow,
  SettingsButton,
  SettingsGroup,
  SettingsRow,
  SettingsSegmented,
  StateWord,
  type Tone,
} from "./rowKit";

// Compact row-idiom panes for the identity, organisation, knowledge and
// advanced settings sections. Every row reads real SDK data; the larger
// operational views remain separate from the default settings path.

const THEME_OPTIONS = ["System", "Light", "Dark"];

// Mirrors the storage-key agreement in theme.ts and AccountProfileSections:
// the server preference is authoritative, localStorage and the document
// dataset follow it so the pre-render bootstrap agrees on next load.
function applyTheme(theme: string) {
  try {
    localStorage.setItem("boltrig-worker-theme", theme);
    const dark = theme === "dark"
      || (theme !== "light" && matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.dataset.theme = dark ? "dark" : "light";
  } catch {
    // A hardened browser may deny storage/media queries; the server
    // preference is still saved.
  }
}

export function CompactYouSection() {
  const [account, setAccount] = useState<MeSettingsResponse | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "unavailable">("loading");
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
        setAccount(result);
        setState("ready");
      })
      .catch(() => { if (!cancelled) setState("unavailable"); });
    return () => { cancelled = true; };
  }, []);

  if (state === "loading") return <p className="muted small">Reading your account…</p>;
  if (state === "unavailable" || !account) {
    return <p className="notice">Your account settings could not be read.</p>;
  }

  const theme = typeof account.settings.theme === "string" ? account.settings.theme : "system";
  const themeLabel = THEME_OPTIONS.find((option) => option.toLowerCase() === theme) ?? "System";

  async function chooseTheme(label: string) {
    const value = label.toLowerCase();
    setMessage("");
    const result = await client.putMeSettings({ key: "theme", value });
    if (result.status !== "ok") {
      setMessage(result.reason ?? "The theme could not be saved.");
      return;
    }
    applyTheme(value);
    setAccount((current) => (current
      ? { ...current, settings: { ...current.settings, theme: value } }
      : current));
  }

  return (
    <>
      <SettingsGroup title="You">
        <SettingsRow
          control={<span className="settings-value">{account.profile.display_name || "—"}</span>}
          title="Name"
        />
        <SettingsRow
          control={(
            <span className="settings-value">
              {account.profile.email || account.profile.id}
              {account.profile.role ? ` · ${account.profile.role}` : ""}
            </span>
          )}
          desc="Identity and role come from the kernel, not from this device."
          title="Signed in as"
        />
      </SettingsGroup>
      <SettingsGroup
        foot={message || "Most people only need their identity and appearance here. Device and developer controls live under Advanced."}
        title="Look"
      >
        <SettingsRow
          control={(
            <SettingsSegmented
              label="Theme"
              onChange={(next) => void chooseTheme(next)}
              options={THEME_OPTIONS}
              value={themeLabel}
            />
          )}
          tech="theme"
          title="Theme"
        />
      </SettingsGroup>
    </>
  );
}

export function CompactOrganisationSection() {
  const [organisation, setOrganisation] = useState<OrganisationView | null>(null);
  const [workspaces, setWorkspaces] = useState<WorkspaceView[] | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "unavailable">("loading");

  useEffect(() => {
    let cancelled = false;
    if (typeof client.currentOrg !== "function") {
      setState("unavailable");
      return;
    }
    void Promise.all([
      client.currentOrg(),
      typeof client.workspaces === "function"
        ? client.workspaces().catch(() => null)
        : Promise.resolve(null),
    ])
      .then(([orgResult, workspaceResult]) => {
        if (cancelled) return;
        setOrganisation(orgResult.organisation);
        setWorkspaces(workspaceResult?.workspaces ?? null);
        setState("ready");
      })
      .catch(() => { if (!cancelled) setState("unavailable"); });
    return () => { cancelled = true; };
  }, []);

  if (state === "loading") return <p className="muted small">Reading the organisation…</p>;
  if (state === "unavailable" || !organisation) {
    return <p className="notice">The organisation is not readable with your current role.</p>;
  }

  return (
    <SettingsGroup
      foot="Members, invitations and workspace changes live in the full Organisation surface on a desktop."
      title="This workspace's organisation"
    >
      <SettingsRow
        control={<span className="settings-value">{organisation.name}</span>}
        tech={organisation.slug}
        title="Organisation"
      />
      <SettingsRow
        control={(
          <StateWord tone={organisation.require_two_factor ? "green" : "amber"}>
            {organisation.require_two_factor ? "required" : "optional"}
          </StateWord>
        )}
        title="Two-factor sign-in"
      />
      <SettingsRow
        control={(
          <span className="settings-value">
            {organisation.allow_own_ai_keys ? "allowed" : "not allowed"}
          </span>
        )}
        desc="Whether members may bring their own model keys."
        title="Own AI keys"
      />
      {workspaces && (
        <SettingsRow
          control={<span className="settings-value">{workspaces.length}</span>}
          title="Workspaces you can see"
        />
      )}
    </SettingsGroup>
  );
}

function providerTone(provider: KnowledgeProvider): { tone: Tone; state: string } {
  if (!provider.enabled) return { tone: "unknown", state: "off" };
  if (provider.health === "ok") return { tone: "green", state: "fine" };
  if (provider.health === "degraded") return { tone: "amber", state: "struggling" };
  if (provider.health === "down") return { tone: "red", state: "down" };
  return { tone: "unknown", state: provider.health || "unknown" };
}

export function CompactKnowledgeSection() {
  const [providers, setProviders] = useState<KnowledgeProvider[] | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "unavailable">("loading");

  useEffect(() => {
    let cancelled = false;
    if (typeof client.knowledgeProviders !== "function") {
      setState("unavailable");
      return;
    }
    void client.knowledgeProviders()
      .then((result) => {
        if (cancelled) return;
        setProviders(result.providers ?? []);
        setState("ready");
      })
      .catch(() => { if (!cancelled) setState("unavailable"); });
    return () => { cancelled = true; };
  }, []);

  if (state === "loading") return <p className="muted small">Reading knowledge providers…</p>;
  if (state === "unavailable" || providers === null) {
    return <p className="notice">Knowledge providers could not be read.</p>;
  }

  return (
    <SettingsGroup
      foot="Uploads, revisions and citations live in the full Knowledge surface on a desktop."
      title="Where knowledge lives"
    >
      {providers.length === 0 ? (
        <SettingsRow
          desc="No knowledge provider is configured in this workspace."
          title="Nothing configured"
        />
      ) : providers.map((provider) => {
        const { tone, state: word } = providerTone(provider);
        return (
          <SettingsRow
            control={<StateWord tone={tone}>{word}</StateWord>}
            desc={provider.role}
            key={provider.id}
            tech={provider.id}
            title={provider.display_name}
          />
        );
      })}
    </SettingsGroup>
  );
}

export function CompactAdvancedSection() {
  return (
    <>
      <SettingsGroup title="This device">
        <SettingsRow
          control={(
            <span className="settings-value">
              {isDesktop ? "Tauri desktop shell" : "Browser session"}
            </span>
          )}
          desc="Sign-in uses the same secure browser session cookie either way."
          title="Running in"
        />
        <DeveloperDetailsRow />
      </SettingsGroup>
      <SettingsGroup
        foot="Device enrolment, desktop updates and the security defaults live in the full Advanced surface on a desktop."
        title="Session"
      >
        <SettingsRow
          control={(
            <SettingsButton
              label="Sign out"
              onClick={() => void client.logout().finally(() => window.location.reload())}
              tone="danger"
            />
          )}
          desc="Revokes the current browser session cookie. Other sessions stay visible and revocable under You."
          title="Signed in to Boltrig"
        />
      </SettingsGroup>
    </>
  );
}
