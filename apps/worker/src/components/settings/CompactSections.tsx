import { useEffect, useState } from "react";
import type {
  KnowledgeMutationResponse,
  KnowledgeProvider,
  MeSettingsResponse,
  MeNotificationItem,
  NotificationCatalogue,
  OrganisationView,
  WorkspaceView,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";
import {
  characterFromSettings,
  characterToSettings,
  loadCharacter,
  saveCharacterLocal,
  type CharacterId,
} from "../../character";
import { listCharacters } from "../characters";
import { isDesktop } from "../../desktop";
import {
  ExactApprovalFinalizer,
  useExactApprovalFinalizer,
} from "../ExactApprovalFinalizer";
import {
  appearanceFromSettings,
  appearanceToSettings,
  loadAppearance,
  saveAppearanceLocal,
  type Appearance,
  type AppearanceDensity,
  type FontScale,
  type ThemePreference,
} from "../../theme";
import {
  DeveloperDetailsRow,
  SettingsButton,
  SettingsGroup,
  SettingsRow,
  SettingsSelect,
  SettingsSegmented,
  SettingsToggle,
  StateWord,
  type Tone,
} from "./rowKit";

// Compact row-idiom panes for the identity, organisation, knowledge and
// advanced settings sections. Every row reads real SDK data; the larger
// operational views remain separate from the default settings path.

const THEME_OPTIONS = ["System", "Dark", "Light"];
const DENSITY_OPTIONS = ["Comfortable", "Compact"];
const TEXT_SIZE_OPTIONS = ["Small", "Normal", "Large"];
// Built from the registry, not from a list here: a character that installs
// itself must appear in its own setting without editing this file.
const BODY_OPTIONS = listCharacters().map((character) => character.name);
const APPEARANCE_TITLES = new Set([
  "Theme",
  "Companion",
  "Density",
  "Text size",
  "Reduced motion",
  "High contrast",
]);

const themeValues: Record<string, ThemePreference> = {
  System: "system",
  Dark: "dark",
  Light: "light",
};
const bodyValues: Record<string, CharacterId> = Object.fromEntries(
  listCharacters().map((character) => [character.name, character.id]),
);
const densityValues: Record<string, AppearanceDensity> = {
  Comfortable: "comfortable",
  Compact: "compact",
};
const textSizeValues: Record<string, FontScale> = {
  Small: "0.9",
  Normal: "1",
  Large: "1.1",
  "Extra large": "1.25",
};

function labelFor<T extends string>(value: T, values: Record<string, T>, fallback: string): string {
  return Object.entries(values).find(([, candidate]) => candidate === value)?.[0] ?? fallback;
}

export function isAppearanceSettingsRow(title: string): boolean {
  return APPEARANCE_TITLES.has(title);
}

function AppearanceGroup({
  appearance,
  busy,
  character,
  message,
  onChange,
  onChangeCharacter,
  titles,
}: {
  appearance: Appearance;
  busy: boolean;
  character: CharacterId;
  message: string;
  onChange(next: Appearance): void;
  onChangeCharacter(next: CharacterId): void;
  titles?: Set<string>;
}) {
  const showTheme = !titles || titles.has("Theme");
  // Companion remains a real, searchable persisted setting, but it is not one
  // of the three visible rows in the decided Look card. Keeping it search-only
  // preserves the target's Theme/Density/Text-size stack and its exact fold.
  const showBody = Boolean(titles?.has("Companion"));
  const showDensity = !titles || titles.has("Density");
  const showText = !titles || titles.has("Text size");
  const showMotion = !titles || titles.has("Reduced motion");
  const showContrast = !titles || titles.has("High contrast");
  if (!showTheme && !showBody && !showDensity && !showText && !showMotion && !showContrast) {
    return null;
  }

  const textOptions = appearance.fontScale === "1.25"
    ? [...TEXT_SIZE_OPTIONS, "Extra large"]
    : TEXT_SIZE_OPTIONS;
  const advanced = [
    showMotion ? (
      <SettingsRow
        control={(
          <SettingsToggle
            disabled={busy}
            label="Reduced motion"
            on={appearance.reducedMotion}
            onToggle={(reducedMotion) => onChange({ ...appearance, reducedMotion })}
          />
        )}
        desc="Removes transitions and animation"
        key="reduced-motion"
        tech="a11y.reduced_motion"
        title="Reduced motion"
      />
    ) : null,
    showContrast ? (
      <SettingsRow
        control={(
          <SettingsToggle
            disabled={busy}
            label="High contrast"
            on={appearance.highContrast}
            onToggle={(highContrast) => onChange({ ...appearance, highContrast })}
          />
        )}
        desc="Stronger borders and text"
        key="high-contrast"
        tech="a11y.high_contrast"
        title="High contrast"
      />
    ) : null,
    !titles ? (
      <SettingsRow
        control={(
          <SettingsSelect
            disabled
            label="Language"
            onChange={() => {}}
            options={["Auto detect", "English", "Deutsch", "Français"]}
            value="Auto detect"
          />
        )}
        key="language"
        title="Language"
      />
    ) : null,
  ].filter((row): row is React.ReactElement => row !== null);

  return (
    <SettingsGroup
      advanced={titles ? undefined : advanced}
      foot={message || undefined}
      title="Look"
    >
      {showTheme && (
        <SettingsRow
          control={(
            <SettingsSegmented
              disabled={busy}
              label="Theme"
              onChange={(label) => onChange({ ...appearance, theme: themeValues[label] ?? "system" })}
              options={THEME_OPTIONS}
              value={labelFor(appearance.theme, themeValues, "System")}
            />
          )}
          tech="theme"
          title="Theme"
        />
      )}
      {showBody && (
        <SettingsRow
          control={(
            <SettingsSegmented
              disabled={busy}
              label="Companion"
              onChange={(label) => onChangeCharacter(bodyValues[label] ?? "familiar")}
              options={BODY_OPTIONS}
              value={labelFor(character, bodyValues, "Familiar")}
            />
          )}
          desc="Choose the body shown on the Stage. The Familiar has a private animated presence; Jarvis visualises measured runtime state."
          tech="agent.character"
          title="Companion"
        />
      )}
      {showDensity && (
        <SettingsRow
          control={(
            <SettingsSegmented
              disabled={busy}
              label="Density"
              onChange={(label) => onChange({ ...appearance, density: densityValues[label] ?? "comfortable" })}
              options={DENSITY_OPTIONS}
              value={labelFor(appearance.density, densityValues, "Comfortable")}
            />
          )}
          tech="density"
          title="Density"
        />
      )}
      {showText && (
        <SettingsRow
          control={(
            <SettingsSegmented
              disabled={busy}
              label="Text size"
              onChange={(label) => onChange({ ...appearance, fontScale: textSizeValues[label] ?? "1" })}
              options={textOptions}
              value={labelFor(appearance.fontScale, textSizeValues, "Normal")}
            />
          )}
          tech="font_scale"
          title="Text size"
        />
      )}
      {titles && advanced}
    </SettingsGroup>
  );
}

function useAppearanceSettings() {
  const [account, setAccount] = useState<MeSettingsResponse | null>(null);
  const [appearance, setAppearance] = useState<Appearance>(() => loadAppearance());
  const [character, setCharacter] = useState<CharacterId>(() => loadCharacter());
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
        const serverAppearance = appearanceFromSettings(result.settings);
        const serverCharacter = characterFromSettings(result.settings);
        setAccount(result);
        setAppearance(serverAppearance);
        saveAppearanceLocal(serverAppearance);
        setCharacter(serverCharacter);
        saveCharacterLocal(serverCharacter);
        setState("ready");
      })
      .catch(() => { if (!cancelled) setState("unavailable"); });
    return () => { cancelled = true; };
  }, []);

  async function changeAppearance(next: Appearance) {
    if (busy) return;
    const previous = appearance;
    setBusy(true);
    setMessage("");
    setAppearance(next);
    saveAppearanceLocal(next);
    try {
      const result = await client.putMeSettings({ settings: appearanceToSettings(next) });
      if (result.status !== "ok") {
        setAppearance(previous);
        saveAppearanceLocal(previous);
        setMessage(result.reason ?? "Your appearance could not be saved.");
        return;
      }
      setAccount((current) => (current
        ? { ...current, settings: { ...current.settings, ...appearanceToSettings(next) } }
        : current));
    } catch {
      setAppearance(previous);
      saveAppearanceLocal(previous);
      setMessage("Your appearance could not be saved.");
    } finally {
      setBusy(false);
    }
  }

  // Saved through the same settings bag but as its own key and call so the
  // Stage selection keeps an independent local mirror and change event.
  async function changeCharacter(next: CharacterId) {
    if (busy) return;
    const previous = character;
    setBusy(true);
    setMessage("");
    setCharacter(next);
    saveCharacterLocal(next);
    try {
      const result = await client.putMeSettings({ settings: characterToSettings(next) });
      if (result.status !== "ok") {
        setCharacter(previous);
        saveCharacterLocal(previous);
        setMessage(result.reason ?? "Your companion could not be saved.");
        return;
      }
      setAccount((current) => (current
        ? { ...current, settings: { ...current.settings, ...characterToSettings(next) } }
        : current));
    } catch {
      setCharacter(previous);
      saveCharacterLocal(previous);
      setMessage("Your companion could not be saved.");
    } finally {
      setBusy(false);
    }
  }

  return {
    account, appearance, busy, changeAppearance, changeCharacter, character,
    message, state,
  };
}

export function CompactYouSection() {
  const {
    account, appearance, busy, changeAppearance, changeCharacter, character, message, state,
  } = useAppearanceSettings();

  if (state === "loading") return <p className="muted small">Reading your account…</p>;
  if (state === "unavailable" || !account) {
    return <p className="notice">Your account settings could not be read.</p>;
  }

  return (
    <>
      <AppearanceGroup
        appearance={appearance}
        busy={busy}
        character={character}
        message={message}
        onChange={(next) => void changeAppearance(next)}
        onChangeCharacter={(next) => void changeCharacter(next)}
      />
      <CompactReachingYouSection />
      <CompactTalkingToItSection />
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
    </>
  );
}

function eventEnabled(prefs: MeNotificationItem[], eventType: string): boolean {
  return prefs.some((pref) => pref.event_type === eventType && pref.enabled);
}

function eventAvailable(catalogue: NotificationCatalogue, eventType: string): boolean {
  return catalogue.events.some((event) => event.id === eventType);
}

function CompactReachingYouSection() {
  const [prefs, setPrefs] = useState<MeNotificationItem[]>([]);
  const [catalogue, setCatalogue] = useState<NotificationCatalogue>({
    events: [],
    transports: [],
  });
  const [state, setState] = useState<"loading" | "ready" | "unavailable">("loading");

  useEffect(() => {
    let cancelled = false;
    if (typeof client.meNotifications !== "function") {
      setState("unavailable");
      return;
    }
    void client.meNotifications()
      .then((result) => {
        if (cancelled) return;
        setPrefs(result.prefs);
        setCatalogue(result.catalogue);
        setState("ready");
      })
      .catch(() => { if (!cancelled) setState("unavailable"); });
    return () => { cancelled = true; };
  }, []);

  const approvalRoutes = prefs.filter((pref) => pref.event_type === "approval" && pref.enabled);
  const approvalDestinations = [...new Set(approvalRoutes.map((pref) => {
    const transport = catalogue.transports.find((item) => item.id === pref.channel);
    const target = transport?.targets.find((item) => item.id === pref.target);
    return [transport?.label ?? pref.channel, target?.label ?? pref.target].filter(Boolean).join(" · ");
  }))];
  const destinationOptions = approvalDestinations.length > 0
    ? approvalDestinations
    : [state === "loading" ? "Reading routes…" : "No verified route"];

  function eventRow(title: string, eventType: string, desc: string) {
    const available = state === "ready" && eventAvailable(catalogue, eventType);
    return (
      <SettingsRow
        control={(
          <SettingsToggle
            disabled
            label={title}
            on={available && eventEnabled(prefs, eventType)}
            onToggle={() => {}}
          />
        )}
        desc={desc}
        key={eventType}
        title={title}
      />
    );
  }

  return (
    <>
      <SettingsGroup
      advanced={[
        eventRow("Escalations", "escalation", "A sub-agent asked for more authority than it has."),
        eventRow("Budget warnings", "budget_warning", "Spend crossed the warning threshold."),
        eventRow("Failures", "failure", "A run failed or a connection degraded."),
        eventRow("Work status changes", "work_status", "Every lane change. Noisy by design."),
      ]}
      title="Reaching you"
      >
        {eventRow(
          "When something needs approving",
          "approval",
          "The one interruption worth having",
        )}
        <SettingsRow
          control={(
            <SettingsSelect
              disabled
              label="Send approval notifications to"
              onChange={() => {}}
              options={destinationOptions}
              value={destinationOptions[0]!}
            />
          )}
          title="Send those to"
        />
        <SettingsRow
          control={<span className="settings-value">Unavailable</span>}
          desc="Only approvals and failures get through"
          title="Quiet hours"
        />
      </SettingsGroup>
      {state === "unavailable" && (
        <span className="settings-visually-hidden">Notification routes could not be read. No destination is inferred on this device.</span>
      )}
      <span className="settings-visually-hidden">The live notification contract has no quiet-hours field, so this client cannot pretend to set one.</span>
    </>
  );
}

function CompactTalkingToItSection() {
  return (
    <SettingsGroup
      advanced={[
        <SettingsRow
          control={(
            <SettingsSelect disabled label="Voice" onChange={() => {}} options={["Even", "Warm", "Brisk"]} value="Even" />
          )}
          key="voice"
          title="Voice"
        />,
        <SettingsRow
          control={(
            <SettingsSelect disabled label="Keep transcripts" onChange={() => {}} options={["7 days", "30 days", "90 days", "Do not keep"]} value="7 days" />
          )}
          key="transcripts"
          title="Keep transcripts"
        />,
        <SettingsRow
          control={<SettingsToggle disabled label="Dictation" on={false} onToggle={() => {}} />}
          desc="The microphone types for you rather than starting a call"
          key="dictation"
          title="Dictation"
        />,
      ]}
      foot="A call goes through exactly what a message does. Same checks, same record, plus a transcript."
      title="Talking to it"
    >
      <SettingsRow
        control={(
          <SettingsToggle disabled label="Take calls" on={false} onToggle={() => {}} />
        )}
        desc="Speak to boltrig, and to work already running"
        title="Take calls"
      />
      <SettingsRow
        control={(
          <SettingsToggle disabled label="Hold the line at a gate" on onToggle={() => {}} />
        )}
        desc="A call waits rather than hanging up when something needs you"
        title="Hold the line at a gate"
      />
      <span className="settings-visually-hidden">Availability is checked against the realtime service when a call starts; there is no saved per-user switch.</span>
      <span className="settings-visually-hidden">Always on in this build: a pending approval holds the call and resumes it from the originating chat.</span>
    </SettingsGroup>
  );
}

/** Live appearance rows used by Settings search instead of destination links. */
export function CompactAppearanceSearchResults({ titles }: { titles: string[] }) {
  const {
    appearance, busy, changeAppearance, changeCharacter, character, message, state,
  } = useAppearanceSettings();
  if (state === "loading") return <p className="muted small">Reading your appearance…</p>;
  if (state === "unavailable") {
    return <p className="notice">Your appearance settings could not be read.</p>;
  }
  return (
    <AppearanceGroup
      appearance={appearance}
      busy={busy}
      message={message}
      character={character}
      onChange={(next) => void changeAppearance(next)}
      onChangeCharacter={(next) => void changeCharacter(next)}
      titles={new Set(titles)}
    />
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
  const [message, setMessage] = useState("");
  const mutationFinalizer = useExactApprovalFinalizer<
    { providerId: string; enabled: boolean },
    KnowledgeMutationResponse
  >({
    isCurrent: (input) => providers?.some((provider) => (
      provider.id === input.providerId && provider.enabled !== input.enabled
    )) ?? false,
    replay: (input, approvalId) => client.setKnowledgeProvider(
      input.providerId,
      input.enabled,
      approvalId,
    ),
    onApplied: async (_result, input) => {
      setMessage(`Provider ${input.enabled ? "enabled" : "disabled"}.`);
      await refreshProviders();
    },
    onRefused: (result) => {
      setMessage(result.reason ?? "The approved Knowledge provider change was not applied.");
    },
    onUncertain: async () => {
      await refreshProviders();
    },
  });

  async function refreshProviders() {
    try {
      const result = await client.knowledgeProviders();
      setProviders(result.providers ?? []);
      setState("ready");
    } catch {
      setState("unavailable");
    }
  }

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

  async function setProvider(provider: KnowledgeProvider, enabled: boolean) {
    if (provider.status === "unavailable") {
      setMessage(
        provider.last_error
          ? `${provider.display_name} is unavailable: ${provider.last_error}`
          : `${provider.display_name} is unavailable in this build.`,
      );
      return;
    }
    setMessage("");
    mutationFinalizer.invalidate();
    const input = { providerId: provider.id, enabled };
    try {
      const result = await client.setKnowledgeProvider(provider.id, enabled);
      if (mutationFinalizer.begin(input, result, "Knowledge provider change")) {
        setMessage("Provider change is waiting for approval in the originating chat.");
        return;
      }
      setMessage(result.reason ?? `Provider ${enabled ? "enabled" : "disabled"}.`);
      if (result.status === "ok") await refreshProviders();
    } catch {
      setMessage(
        `${provider.display_name} could not be changed. Its last reported state is unchanged; it is safe to retry.`,
      );
    }
  }

  if (state === "loading") return <p className="muted small">Reading knowledge providers…</p>;
  if (state === "unavailable" || providers === null) {
    return <p className="notice">Knowledge providers could not be read.</p>;
  }

  return (
    <>
      {message && <p className="console-foot" role="status">{message}</p>}
      <ExactApprovalFinalizer controller={mutationFinalizer} />
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
              control={(
                <div className="settings-status">
                  <StateWord tone={tone}>{word}</StateWord>
                  <SettingsToggle
                    disabled={provider.status === "unavailable"}
                    label={`${provider.enabled ? "Disable" : "Enable"} ${provider.display_name}`}
                    on={provider.enabled}
                    onToggle={(enabled) => void setProvider(provider, enabled)}
                  />
                </div>
              )}
              desc={provider.last_error ? `${provider.role} · ${provider.last_error}` : provider.role}
              key={provider.id}
              tech={provider.id}
              title={provider.display_name}
            />
          );
        })}
      </SettingsGroup>
    </>
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
