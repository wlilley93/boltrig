import { useState } from "react";

import { client } from "../../client";
import { AuthCard } from "./AuthShell";
import { tokenFromHash } from "./routing";

export function RequestPasswordResetScreen({
  initialEmail,
  onDone,
}: {
  initialEmail: string;
  onDone(): void;
}) {
  const [email, setEmail] = useState(initialEmail);
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy || !email.trim()) return;
    setBusy(true);
    setError("");
    try {
      const result = await client.requestPasswordReset({ email: email.trim() });
      if (result.status === "ok") setSent(true);
      else setError(result.reason ?? "Password recovery is temporarily unavailable.");
    } catch {
      setError("Could not reach Boltrig. Try again.");
    } finally {
      setBusy(false);
    }
  }

  if (sent) return <PasswordResetSent onDone={onDone} />;
  return (
    <AuthCard title="Reset your password" lead="Enter the email used for your Boltrig account.">
      <form className="auth-form" onSubmit={submit}>
        <label>
          <span>Email</span>
          <input type="email" autoComplete="username" autoFocus value={email} onChange={(event) => setEmail(event.target.value)} />
        </label>
        {error && <p className="auth-error" role="alert">{error}</p>}
        <div className="auth-actions">
          <button type="button" className="secondary-button" onClick={onDone}>Back</button>
          <button className="primary-button" disabled={busy || !email.trim()}>
            {busy ? "Sending…" : "Send reset link"}
          </button>
        </div>
      </form>
    </AuthCard>
  );
}

function PasswordResetSent({ onDone }: { onDone(): void }) {
  return (
    <AuthCard
      title="Check your email"
      lead="If the account can be recovered, reset instructions have been sent."
    >
      <div className="auth-handoff">
        <p>The same message is shown whether or not an account exists.</p>
        <button className="primary-button" onClick={onDone}>Back to sign in</button>
      </div>
    </AuthCard>
  );
}

export function ResetPasswordScreen({ onDone }: { onDone(): void }) {
  const token = tokenFromHash();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [complete, setComplete] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!token || password.length < 12 || password !== confirm || busy) return;
    setBusy(true);
    setError("");
    try {
      const result = await client.confirmPasswordReset({ token, new_password: password });
      if (result.status === "ok") setComplete(true);
      else setError(result.reason ?? "This reset link could not be used.");
    } catch {
      setError("Could not reset the password.");
    } finally {
      setBusy(false);
    }
  }

  if (complete) return <ResetPasswordComplete onDone={onDone} />;
  if (!token) return <MissingResetToken onDone={onDone} />;
  return (
    <AuthCard title="Choose a new password" lead="This link is expiring and can be used once.">
      <form className="auth-form" onSubmit={submit}>
        <label><span>New password</span><input type="password" autoComplete="new-password" autoFocus value={password} onChange={(event) => setPassword(event.target.value)} /></label>
        <label><span>Confirm new password</span><input type="password" autoComplete="new-password" value={confirm} onChange={(event) => setConfirm(event.target.value)} /></label>
        {password.length > 0 && password.length < 12 && <p className="auth-error">Use at least 12 characters.</p>}
        {confirm.length > 0 && password !== confirm && <p className="auth-error">The passwords do not match.</p>}
        {error && <p className="auth-error" role="alert">{error}</p>}
        <div className="auth-actions">
          <button type="button" className="secondary-button" onClick={onDone}>Back</button>
          <button className="primary-button" disabled={busy || password.length < 12 || password !== confirm}>
            {busy ? "Resetting…" : "Reset password"}
          </button>
        </div>
      </form>
    </AuthCard>
  );
}

function ResetPasswordComplete({ onDone }: { onDone(): void }) {
  return (
    <AuthCard title="Password reset" lead="Your new password is ready to use.">
      <div className="auth-handoff">
        <p>All existing browser sessions have been signed out.</p>
        <button className="primary-button" onClick={onDone}>Go to sign in</button>
      </div>
    </AuthCard>
  );
}

function MissingResetToken({ onDone }: { onDone(): void }) {
  return (
    <AuthCard title="Reset your password" lead="This reset link is incomplete.">
      <div className="auth-handoff">
        <p className="auth-error">The reset token is missing. Request a new link.</p>
        <button className="secondary-button" onClick={onDone}>Back to sign in</button>
      </div>
    </AuthCard>
  );
}
