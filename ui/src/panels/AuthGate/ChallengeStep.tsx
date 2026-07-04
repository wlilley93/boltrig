import { useState } from "react";

import { api } from "@/api/client";
import { markAuthenticated } from "@/auth";
import { AuthShell } from "@/panels/AuthGate/AuthShell";

export function ChallengeStep({ challengeToken }: { challengeToken: string }) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (busy || !code.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.twoFactorChallenge({
        challenge_token: challengeToken,
        code: code.trim(),
      });
      if (res.status === "ok") {
        markAuthenticated(res.user ?? null);
        return;
      }
      setError(res.reason ?? "That code was not accepted. Try again.");
    } catch {
      setError("Could not reach the server. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthShell
      title="Two-factor verification"
      lead="Enter the 6-digit code from your authenticator app, or a recovery code."
    >
      <form className="auth-form" onSubmit={submit}>
        <label className="field">
          <span>Authentication code</span>
          <input
            type="text"
            inputMode="text"
            autoComplete="one-time-code"
            autoFocus
            value={code}
            onChange={(ev) => setCode(ev.target.value)}
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
          disabled={busy || !code.trim()}
        >
          {busy ? "Verifying..." : "Verify and sign in"}
        </button>
      </form>
    </AuthShell>
  );
}
