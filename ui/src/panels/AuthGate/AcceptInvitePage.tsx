import { useState } from "react";

import { api } from "@/api/client";
import { navigate } from "@/router";
import { AuthShell } from "@/panels/AuthGate/AuthShell";

const MIN_PASSWORD_LENGTH = 12; // mirrors boltrig/identity/passwords.py

// Read a query param off the current hash (#/accept-invite?token=...). The
// router only surfaces ?run, so the token is parsed here.
function hashParam(name: string): string {
  const q = window.location.hash.split("?")[1] ?? "";
  return new URLSearchParams(q).get(name) ?? "";
}

type AcceptInviteFormProps = {
  password: string;
  setPassword: (value: string) => void;
  confirm: string;
  setConfirm: (value: string) => void;
  busy: boolean;
  error: string | null;
  tooShort: boolean;
  mismatch: boolean;
  canSubmit: boolean;
  onSubmit: (e: React.FormEvent) => void;
};

function AcceptInviteForm({
  password,
  setPassword,
  confirm,
  setConfirm,
  busy,
  error,
  tooShort,
  mismatch,
  canSubmit,
  onSubmit,
}: AcceptInviteFormProps) {
  return (
    <form className="auth-form" onSubmit={onSubmit}>
      <label className="field">
        <span>New password</span>
        <input
          type="password"
          autoComplete="new-password"
          value={password}
          autoFocus
          onChange={(ev) => setPassword(ev.target.value)}
        />
      </label>
      <label className="field">
        <span>Confirm password</span>
        <input
          type="password"
          autoComplete="new-password"
          value={confirm}
          onChange={(ev) => setConfirm(ev.target.value)}
        />
      </label>
      <p className="ux-hint">
        Use at least {MIN_PASSWORD_LENGTH} characters. A longer passphrase is
        stronger than a short complex one.
      </p>
      {tooShort && (
        <p className="error" role="alert">
          Password must be at least {MIN_PASSWORD_LENGTH} characters.
        </p>
      )}
      {mismatch && (
        <p className="error" role="alert">
          The two passwords do not match.
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <button
        type="submit"
        className="btn btn--primary auth-form__submit"
        disabled={!canSubmit}
      >
        {busy ? "Setting password..." : "Set password and continue"}
      </button>
    </form>
  );
}

function AcceptInviteDone({ email }: { email: string | null }) {
  return (
    <AuthShell
      title="Account created"
      lead={email ? `Your password is set for ${email}.` : "Your password is set."}
    >
      <p className="ok" role="status">
        You can now sign in with your email and new password.
      </p>
      <button
        type="button"
        className="btn btn--primary auth-form__submit"
        onClick={() => navigate("/")}
      >
        Go to sign in
      </button>
    </AuthShell>
  );
}

function AcceptInviteMissing() {
  return (
    <AuthShell
      title="Invitation link"
      lead="This invitation link is incomplete."
    >
      <p className="error" role="alert">
        The invitation token is missing from the link. Ask your administrator
        to resend the invitation.
      </p>
      <button type="button" className="btn auth-form__submit" onClick={() => navigate("/")}>
        Back to sign in
      </button>
    </AuthShell>
  );
}

export function AcceptInvitePage() {
  const [token] = useState(() => hashParam("token"));
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const tooShort = password.length > 0 && password.length < MIN_PASSWORD_LENGTH;
  const mismatch = confirm.length > 0 && confirm !== password;
  const canSubmit =
    !!token &&
    password.length >= MIN_PASSWORD_LENGTH &&
    confirm === password &&
    !busy;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.acceptInvite({ token, password });
      if (res.status === "ok") {
        setDone(res.email ?? null);
        return;
      }
      // Surface the backend reason faithfully (invalid/expired token, weak
      // password) - it is a safe, generic message by construction.
      setError(res.reason ?? "This invitation could not be accepted.");
    } catch {
      setError("Could not reach the server. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  if (done !== null) return <AcceptInviteDone email={done} />;
  if (!token) return <AcceptInviteMissing />;

  return (
    <AuthShell title="Set your password" lead="Choose a password to finish setting up your account.">
      <AcceptInviteForm
        password={password}
        setPassword={setPassword}
        confirm={confirm}
        setConfirm={setConfirm}
        busy={busy}
        error={error}
        tooShort={tooShort}
        mismatch={mismatch}
        canSubmit={canSubmit}
        onSubmit={submit}
      />
    </AuthShell>
  );
}
