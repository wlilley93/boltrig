import { useEffect, useState } from "react";
import type {
  MeSettingsResponse,
  MeNotificationItem,
  NotificationCatalogue,
  OrganisationView,
  WorkspaceView,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";

import { CompactReachingYouSection } from "./ReachingYouSection";
import { saveCompanion } from "./companionSave";
import {
  characterFromSettings,
  characterToSettings,
  loadCharacter,
  saveCharacterLocal,
  saveSkinLocal,
  type CharacterId,
} from "../../character";
import { isDesktop } from "../../desktop";
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
import { CompanionRows } from "./CompanionRows";
import { ReadRepliesSetting } from "./ReadRepliesSetting";
// Compact row-idiom panes for the identity, organisation, knowledge and
// advanced settings sections. Every row reads real SDK data; the larger
// operational views remain separate from the default settings path.

const THEME_OPTIONS = ["System", "Dark", "Light"];
const DENSITY_OPTIONS = ["Comfortable", "Compact"];
const TEXT_SIZE_OPTIONS = ["Small", "Normal", "Large"];
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
  // Companion remains searchable but outside the three-row Look card. That
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
        <CompanionRows
          busy={busy}
          character={character}
          onChangeCharacter={onChangeCharacter}
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
  // Stage selection keeps an independent local mirror and change event. The
  // server half (save, rollback, adoption announcement) lives in
  // companionSave.ts so this debt file only shrinks.
  async function changeCharacter(next: CharacterId) {
    if (busy) return;
    const previous = character;
    setBusy(true);
    setMessage("");
    setCharacter(next);
    saveCharacterLocal(next);
    try {
      await saveCompanion(next, previous, { setAccount, setCharacter, setMessage });
    } finally {
      setBusy(false);
    }
  }

  return {
    account, appearance, busy, changeAppearance, changeCharacter, character,
    message, state,
  };
}

/** Where this console came from, and the way back to it.
 *
 *  A PLAIN LINK, NOT A CLIENT CALL. Everything else in this file asks the
 *  agent; this asks for a different page of the same site. The workspace view
 *  is served by the control plane at the same origin, so the session cookie
 *  travels with an ordinary navigation and the person arrives already signed
 *  in. Routing it through the client would mean inventing a method for
 *  "navigate", and an absent one would hide the only way back.
 *
 *  WHY THE WAY BACK MATTERS. This console is what "/" opens once a team box is
 *  answering, which is the right default - people want their agent. But
 *  everything ABOUT the box lives on the other side: the address a desktop
 *  client connects to, the members of the team, and adding another box. Without
 *  a door here, arriving at the agent would be one-way for exactly the people
 *  who have one.
 *
 *  It renders unconditionally rather than probing for anything. There is no
 *  call that can fail, and a door that hides itself when it cannot verify the
 *  room behind it is worse than one that opens onto a page saying why.
 */
function WorkspacesRow() {
  return (
    <SettingsRow
      control={(
        // An ANCHOR wearing the button's own class, not a button that
        // navigates. It carries the same weight visually and still behaves
        // like a link: middle-click and open-in-new-tab work, and it shows its
        // destination on hover. A button would take all three away for nothing.
        <a className="settings-kit-button" href="/?workspace">
          Open
        </a>
      )}
      desc="Your team boxes, the address each answers on, and adding another."
      title="Your workspaces"
    />
  );
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
          desc="Your workspace manages your identity and role."
          title="Signed in as"
        />
        <WorkspacesRow />
      </SettingsGroup>
    </>
  );
}

function CompactTalkingToItSection() {
  return <SettingsGroup
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
      <ReadRepliesSetting />
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
      <span className="settings-visually-hidden">Call availability is checked when a call starts.</span>
      <span className="settings-visually-hidden">Calls wait for approval and resume from the originating chat.</span>
    </SettingsGroup>;
}

/** Live appearance rows used by Settings search instead of destination links. */
// They share the same caller-scoped settings record as the full appearance pane.
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
    <SettingsGroup title="This workspace's organisation">
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

export function CompactAdvancedSection() {
  return (
    <>
      <SettingsGroup title="This device">
        <SettingsRow
          control={(
            <span className="settings-value">
              {isDesktop ? "Desktop app" : "Web browser"}
            </span>
          )}
          desc="Your sign-in stays protected in either app."
          title="Running in"
        />
        <DeveloperDetailsRow />
      </SettingsGroup>
      <SettingsGroup title="Session">
        <SettingsRow
          control={(
            <SettingsButton
              label="Sign out"
              onClick={() => void client.logout().finally(() => window.location.reload())}
              tone="danger"
            />
          )}
          desc="Signs out this account session. Computer trust stays until you revoke it."
          title="Signed in to Boltrig"
        />
      </SettingsGroup>
    </>
  );
}
