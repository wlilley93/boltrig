import { useCallback, useEffect, useState } from "react";

import { hasDesktopRuntime } from "../../desktop";
import {
  localAgentStatus,
  signInLocalAgent,
  signOutLocalAgent,
  type LocalAgentStatus,
} from "../../localAgentClient";
import { SettingsButton, SettingsGroup, SettingsRow, StateWord } from "./rowKit";

// Settings → Advanced, desktop only. Local tasks run on this computer with
// the user's own runtime sign-in, which the app keeps in a home of its own
// (never the personal one), so the sign-in is made and removed from here.

type Phase =
  | { kind: "loading" }
  | { kind: "idle"; status: LocalAgentStatus }
  | { kind: "signing_in"; code: string | null; url: string | null; opened: boolean }
  | { kind: "signing_out" };

const UNAVAILABLE: LocalAgentStatus = {
  runtime: "local",
  state: "unavailable",
  source: null,
  version: null,
  active: false,
  signed_in: false,
  reason: "local_agent_status_unavailable",
};

export function LocalRuntimeSection() {
  if (!hasDesktopRuntime()) return null;
  return <LocalRuntimeGroup />;
}

function LocalRuntimeGroup() {
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [message, setMessage] = useState("");

  const refresh = useCallback(async () => {
    const status = await localAgentStatus().catch(() => UNAVAILABLE);
    setPhase({ kind: "idle", status });
  }, []);

  useEffect(() => {
    let active = true;
    void localAgentStatus()
      .catch(() => UNAVAILABLE)
      .then((status) => { if (active) setPhase({ kind: "idle", status }); });
    return () => { active = false; };
  }, []);

  async function signIn() {
    setMessage("");
    setPhase({ kind: "signing_in", code: null, url: null, opened: false });
    try {
      await signInLocalAgent((event) => {
        if (event.type === "code") {
          setPhase({ kind: "signing_in", code: event.code, url: event.url, opened: event.opened });
        }
      });
      setMessage("Signed in. Local tasks can now use your account.");
    } catch (reason) {
      setMessage(signInMessage(reason));
    } finally {
      await refresh();
    }
  }

  async function signOut() {
    setMessage("");
    setPhase({ kind: "signing_out" });
    try {
      await signOutLocalAgent();
      setMessage("Signed out. Local tasks will ask you to sign in again.");
    } catch {
      setMessage("This computer could not remove the local sign-in. It is safe to retry.");
    } finally {
      await refresh();
    }
  }

  return (
    <SettingsGroup foot={message || undefined} title="Local tasks">
      <SettingsRow
        control={<PhaseControl onSignIn={() => void signIn()} onSignOut={() => void signOut()} phase={phase} />}
        desc={describe(phase)}
        tech="local_agent_sign_in"
        title="Local runtime sign-in"
      />
    </SettingsGroup>
  );
}

function describe(phase: Phase): string {
  if (phase.kind === "loading") return "Checking the local runtime…";
  if (phase.kind === "signing_out") return "Signing out…";
  if (phase.kind === "signing_in") {
    if (!phase.code) return "Starting your sign-in…";
    const where = phase.opened
      ? "the sign-in page that just opened"
      : `the sign-in page at ${phase.url ?? "the address shown"}`;
    return `Enter the code ${phase.code} on ${where}. Waiting for you to finish.`;
  }
  if (phase.status.state !== "ready") return "Local tasks are unavailable on this computer.";
  return phase.status.signed_in
    ? "Local tasks use your own ChatGPT or OpenAI sign-in, kept inside this app."
    : "Local tasks run on this computer with your own ChatGPT or OpenAI sign-in. "
      + "It is kept inside this app and is not shared with anything else on this computer.";
}

function PhaseControl({ onSignIn, onSignOut, phase }: {
  onSignIn(): void;
  onSignOut(): void;
  phase: Phase;
}) {
  if (phase.kind === "loading" || phase.kind === "signing_out") {
    return <span className="settings-value">…</span>;
  }
  if (phase.kind === "signing_in") {
    return (
      <span className="settings-status">
        {phase.code && <code>{phase.code}</code>}
        <SettingsButton label="Cancel" onClick={onSignOut} />
      </span>
    );
  }
  if (phase.status.state !== "ready") return <StateWord tone="amber">unavailable</StateWord>;
  return phase.status.signed_in
    ? (
      <span className="settings-status">
        <StateWord tone="green">signed in</StateWord>
        <SettingsButton label="Sign out" onClick={onSignOut} tone="danger" />
      </span>
    )
    : (
      <span className="settings-status">
        <StateWord tone="amber">not signed in</StateWord>
        <SettingsButton label="Sign in" onClick={onSignIn} />
      </span>
    );
}

function signInMessage(reason: unknown): string {
  const code = String(reason);
  if (code.includes("local_agent_sign_in_cancelled")) return "Sign-in cancelled.";
  if (code.includes("local_agent_sign_in_timed_out")) {
    return "The sign-in code expired. Start again when you are ready.";
  }
  if (code.includes("local_agent_busy")) return "Finish the running local task first.";
  if (code.includes("local_agent_binary")) return "The local runtime is unavailable on this computer.";
  return "The sign-in did not complete. It is safe to retry.";
}
