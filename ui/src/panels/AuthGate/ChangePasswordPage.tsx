// Forced rotation of a provisioning credential ([2026] VJS-COUNTY 8, D7).
//
// Reached when the account still holds the password typed at `boltrig initiate`.
// The session IS valid - the resolver clamps it to this surface and logout, and
// nothing else - so this screen is the only way into the console, and it is the
// reason the clamp is a feature rather than a lockout.
//
// It does not offer a way past. There is no skip and no "remind me later": the
// hazard is that the provisioning credential survives, and a dismissable prompt
// is how it survives.

import { useState } from "react";

import { api } from "@/api/client";
import { markAuthenticated, markUnauthenticated } from "@/auth";
import { AuthShell } from "@/panels/AuthGate/AuthShell";

export function ChangePasswordPage() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Checked here only to spare a round trip and to say WHICH field is wrong. The
  // server decides: strength, the current password, and "must differ" are all
  // re-checked there, because a console is not a place to enforce a credential
  // rule from.
  const mismatch = confirm.length > 0 && next !== confirm;
  const ready = current.length > 0 && next.length > 0 && !mismatch;

  async function onSubmit(ev: React.FormEvent) {
    ev.preventDefault();
    if (!ready || busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.changePassword({
        current_password: current,
        new_password: next,
      });
      if (res.status === "ok") {
        // The clamp lifts server-side the moment the flag clears; the session in
        // hand is already unclamped, so enter the app rather than force a re-login.
        markAuthenticated(null);
        return;
      }
      setError(res.reason || "That password was not accepted.");
    } catch {
      setError("Could not reach the server. Try again.");
    } finally {
      setBusy(false);
    }
  }

  async function onSignOut() {
    try {
      await api.logout();
    } finally {
      markUnauthenticated();
    }
  }

  return (
    <AuthShell
      title="Choose a new password"
      lead="This account still uses the password it was set up with. That password has been typed into a terminal and is often written down, so it has to be replaced before the console opens."
    >
      <form className="auth-form" onSubmit={onSubmit}>
        <label className="field">
          <span>Current password</span>
          <input
            type="password"
            autoComplete="current-password"
            value={current}
            autoFocus
            onChange={(ev) => setCurrent(ev.target.value)}
          />
        </label>
        <label className="field">
          <span>New password</span>
          <input
            type="password"
            autoComplete="new-password"
            value={next}
            onChange={(ev) => setNext(ev.target.value)}
          />
        </label>
        <label className="field">
          <span>Confirm new password</span>
          <input
            type="password"
            autoComplete="new-password"
            value={confirm}
            onChange={(ev) => setConfirm(ev.target.value)}
          />
        </label>
        {mismatch && (
          <p className="error" role="alert">
            Those do not match.
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
          disabled={busy || !ready}
        >
          {busy ? "Saving..." : "Save and continue"}
        </button>
      </form>
      <p className="auth-card__foot muted">
        <button type="button" className="btn btn--ghost" onClick={onSignOut}>
          Sign out
        </button>
      </p>
    </AuthShell>
  );
}
