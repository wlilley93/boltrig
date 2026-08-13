import { useState } from "react";

import { client, rememberSessionCsrf } from "../../client";
import { isDesktop } from "../../desktop";
import { AuthCard } from "./AuthShell";
import type { GateState } from "./types";

interface LoginScreenProps {
  onChallenge(token: string): void;
  onState(state: GateState): void;
  onForgot(email: string): void;
}

export function LoginScreen({ onChallenge, onState, onForgot }: LoginScreenProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const result = await client.login({ email: email.trim(), password });
      if (result.csrf_token) rememberSessionCsrf(result.csrf_token);
      if (result.status === "ok") return onState("authenticated");
      if (result.status === "2fa_required" && result.challenge_token) {
        return onChallenge(result.challenge_token);
      }
      if (result.status === "password_change_required") {
        return onState("password_change_required");
      }
      if (result.status === "2fa_enrollment_required") return onState("enrollment_required");
      setError(result.reason ?? "Incorrect email or password.");
    } catch {
      setError("Could not reach Boltrig. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard
      title="Welcome back"
      lead={isDesktop
        ? "Sign in to your Boltrig account. This desktop connects to it after authentication."
        : "Sign in to your Boltrig workspace."}
    >
      <form className="auth-form" onSubmit={submit}>
        <label><span>Email</span><input type="email" autoComplete="username" autoFocus value={email} onChange={(event) => setEmail(event.target.value)} /></label>
        <label><span>Password</span><input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>
        {error && <p className="auth-error" role="alert">{error}</p>}
        <button className="primary-button" disabled={busy || !email.trim() || !password}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
      <div className="auth-actions">
        <button type="button" className="secondary-button" onClick={() => onForgot(email)}>
          Forgot password?
        </button>
      </div>
      <p className="auth-foot">Boltrig is invite only. Permanent provider and integration credentials never enter this client.</p>
    </AuthCard>
  );
}
