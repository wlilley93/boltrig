import { useState } from "react";

import { client } from "../../client";
import { AuthCard } from "./AuthShell";
import { tokenFromHash } from "./routing";

export function AcceptInviteScreen({ onDone }: { onDone(): void }) {
  const token = tokenFromHash();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [email, setEmail] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!token || password.length < 12 || password !== confirm) return;
    setBusy(true);
    setError("");
    try {
      const result = await client.acceptInvite({ token, password });
      if (result.status === "ok") setEmail(result.email ?? "");
      else setError(result.reason ?? "This invitation could not be accepted.");
    } catch {
      setError("Could not accept the invitation.");
    } finally {
      setBusy(false);
    }
  }

  if (email !== null) return <InviteAccepted email={email} onDone={onDone} />;
  if (!token) return <MissingInviteToken onDone={onDone} />;
  return (
    <AuthCard title="Accept your invitation" lead="Choose a password to finish creating your Boltrig account.">
      <form className="auth-form" onSubmit={submit}>
        <label><span>New password</span><input type="password" autoComplete="new-password" autoFocus value={password} onChange={(event) => setPassword(event.target.value)} /></label>
        <label><span>Confirm password</span><input type="password" autoComplete="new-password" value={confirm} onChange={(event) => setConfirm(event.target.value)} /></label>
        {password.length > 0 && password.length < 12 && <p className="auth-error">Use at least 12 characters.</p>}
        {confirm.length > 0 && password !== confirm && <p className="auth-error">The passwords do not match.</p>}
        {error && <p className="auth-error" role="alert">{error}</p>}
        <button className="primary-button" disabled={busy || password.length < 12 || password !== confirm}>{busy ? "Creating…" : "Set password"}</button>
      </form>
    </AuthCard>
  );
}

function InviteAccepted({ email, onDone }: { email: string; onDone(): void }) {
  return (
    <AuthCard
      title="Account created"
      lead={email ? `Your password is set for ${email}.` : "Your password is set."}
    >
      <div className="auth-handoff">
        <p>You can now sign in with the password you just chose.</p>
        <button className="primary-button" onClick={onDone}>Go to sign in</button>
      </div>
    </AuthCard>
  );
}

function MissingInviteToken({ onDone }: { onDone(): void }) {
  return (
    <AuthCard title="Accept your invitation" lead="Choose a password to finish creating your Boltrig account.">
      <div className="auth-handoff">
        <p className="auth-error">This invitation link is missing its token. Ask an administrator to resend it.</p>
        <button className="secondary-button" onClick={onDone}>Back to sign in</button>
      </div>
    </AuthCard>
  );
}
