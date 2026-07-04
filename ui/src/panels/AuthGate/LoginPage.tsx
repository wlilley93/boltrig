import { useState } from "react";

import { api } from "@/api/client";
import { markAuthenticated, markEnrollRequired } from "@/auth";
import { AuthShell } from "@/panels/AuthGate/AuthShell";
import { ChallengeStep } from "@/panels/AuthGate/ChallengeStep";

type LoginFormProps = {
  email: string;
  setEmail: (value: string) => void;
  password: string;
  setPassword: (value: string) => void;
  busy: boolean;
  error: string | null;
  onSubmit: (e: React.FormEvent) => void;
};

function LoginForm({
  email,
  setEmail,
  password,
  setPassword,
  busy,
  error,
  onSubmit,
}: LoginFormProps) {
  return (
    <form className="auth-form" onSubmit={onSubmit}>
      <label className="field">
        <span>Email</span>
        <input
          type="email"
          autoComplete="username"
          value={email}
          autoFocus
          onChange={(ev) => setEmail(ev.target.value)}
        />
      </label>
      <label className="field">
        <span>Password</span>
        <input
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(ev) => setPassword(ev.target.value)}
        />
      </label>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <button
        type="submit"
        className="btn btn--primary auth-form__submit"
        disabled={busy || !email.trim() || !password}
      >
        {busy ? "Signing in..." : "Sign in"}
      </button>
    </form>
  );
}

export function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Set only when the backend answers 2fa_required; while set, the challenge step
  // replaces the password form. Null on the ordinary (no-2FA) path.
  const [challengeToken, setChallengeToken] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.login({ email: email.trim(), password });
      if (res.status === "ok") {
        // The response set the httpOnly session cookie + the readable CSRF
        // cookie; nothing sensitive is kept in JS. Flip the gate open.
        markAuthenticated(res.user ?? null);
        return;
      }
      if (res.status === "2fa_required" && res.challenge_token) {
        // D3: the password verified but NO session was issued. Move to the second
        // factor step; the session is issued only when the code verifies.
        setChallengeToken(res.challenge_token);
        return;
      }
      if (res.status === "2fa_enrollment_required") {
        // D4: the org requires 2FA and the user has not enrolled. The enrollment-
        // only session cookie is set; route to the enrollment screen.
        markEnrollRequired();
        return;
      }
      // A generic failure by design: the backend never reveals whether an email
      // exists. 429 carries its own throttle reason.
      setError(res.reason ?? "Incorrect email or password.");
    } catch {
      setError("Could not reach the server. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  if (challengeToken) return <ChallengeStep challengeToken={challengeToken} />;

  return (
    <AuthShell title="Sign in" lead="Sign in to your Boltrig console.">
      <LoginForm
        email={email}
        setEmail={setEmail}
        password={password}
        setPassword={setPassword}
        busy={busy}
        error={error}
        onSubmit={submit}
      />
      <p className="auth-card__foot muted">
        Boltrig is invite only. Ask an administrator for an invitation to create
        an account.
      </p>
    </AuthShell>
  );
}
