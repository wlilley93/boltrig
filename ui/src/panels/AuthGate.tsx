// The first-party auth gate (COUNTY 7). When auth_mode=session and there is no
// session, this stands in front of the whole console: it is the sole
// internet-facing gate that replaces Cloudflare Access. Under the dev header
// resolver (and the e2e smoke) the probe resolves to a principal, so the gate
// never appears and the children render straight through - see auth.ts for the
// deliberate 401-only guard.
//
// Two public pages live here (neither needs a session): the login form, and the
// accept-invite page reached by an invite link carrying a single-use token
// (#/accept-invite?token=...). Everything else is gated behind a live session.

import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import { api } from "../api/client";
import { markAuthenticated, probeSession, useAuth } from "../auth";
import { navigate, useRoute } from "../router";
import { AuthShell } from "@/panels/AuthGate/AuthShell";
import { LoginPage } from "@/panels/AuthGate/LoginPage";

const MIN_PASSWORD_LENGTH = 12; // mirrors boltrig/identity/passwords.py

// Read a query param off the current hash (#/accept-invite?token=...). The
// router only surfaces ?run, so the token is parsed here.
function hashParam(name: string): string {
  const q = window.location.hash.split("?")[1] ?? "";
  return new URLSearchParams(q).get(name) ?? "";
}

function AcceptInvitePage() {
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

  if (done !== null) {
    return (
      <AuthShell
        title="Account created"
        lead={done ? `Your password is set for ${done}.` : "Your password is set."}
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

  if (!token) {
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

  return (
    <AuthShell title="Set your password" lead="Choose a password to finish setting up your account.">
      <form className="auth-form" onSubmit={submit}>
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
    </AuthShell>
  );
}

// The forced-enrollment screen ([2026] VJS-COUNTY 10, D4). Shown when the org
// requires two-factor and the user has not enrolled: the enrollment-only session
// is live but the resolver clamps every other surface, so this is the ONLY thing
// they can reach. Begins enrollment on mount (secret + recovery codes shown ONCE),
// then confirms a code to activate; on success the same session becomes fully
// privileged and the gate opens.
function EnrollFlow() {
  const [begin, setBegin] = useState<{
    secret: string;
    otpauthUri: string;
    recoveryCodes: string[];
  } | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const res = await api.twoFactorEnrollBegin();
        if (cancelled) return;
        if (res.status === "ok" && res.secret && res.otpauth_uri) {
          setBegin({
            secret: res.secret,
            otpauthUri: res.otpauth_uri,
            recoveryCodes: res.recovery_codes ?? [],
          });
        } else {
          setLoadError(res.reason ?? "Could not start two-factor setup.");
        }
      } catch {
        if (!cancelled) setLoadError("Could not reach the server. Please try again.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function confirm(e: React.FormEvent) {
    e.preventDefault();
    if (busy || !code.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.twoFactorVerifyEnroll({ code: code.trim() });
      if (res.status === "ok") {
        // The clamp lifts: the same session is now fully privileged. Enter the app.
        markAuthenticated(null);
        return;
      }
      setError(res.reason ?? "That code was not accepted. Try again.");
    } catch {
      setError("Could not reach the server. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  if (loadError) {
    return (
      <AuthShell title="Two-factor setup" lead="Your organisation requires two-factor authentication.">
        <p className="error" role="alert">
          {loadError}
        </p>
        <button
          type="button"
          className="btn auth-form__submit"
          onClick={() => api.logout().finally(() => navigate("/"))}
        >
          Back to sign in
        </button>
      </AuthShell>
    );
  }

  if (!begin) {
    return (
      <AuthShell title="Two-factor setup" lead="Preparing your authenticator setup...">
        <div className="auth-splash" role="status" aria-live="polite">
          <span className="auth-splash__spinner" aria-hidden="true" />
          <span className="auth-splash__text">Loading...</span>
        </div>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      title="Set up two-factor"
      lead="Your organisation requires two-factor authentication. Add this account to an authenticator app, then confirm a code."
    >
      <div className="auth-2fa__setup">
        <p className="ux-hint">
          Enter this secret key into your authenticator app (Google Authenticator,
          1Password, Authy, ...). Keep it private - it is shown only once.
        </p>
        <code className="auth-2fa__secret" aria-label="Two-factor secret key">
          {begin.secret}
        </code>
        {begin.recoveryCodes.length > 0 && (
          <div className="auth-2fa__recovery">
            <p className="ux-hint">
              Save these one-time recovery codes somewhere safe. Each works once if
              you lose your authenticator. They are shown only now.
            </p>
            <ul className="auth-2fa__codes">
              {begin.recoveryCodes.map((rc) => (
                <li key={rc}>
                  <code>{rc}</code>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
      <form className="auth-form" onSubmit={confirm}>
        <label className="field">
          <span>Enter a 6-digit code to confirm</span>
          <input
            type="text"
            inputMode="numeric"
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
          {busy ? "Confirming..." : "Confirm and continue"}
        </button>
      </form>
    </AuthShell>
  );
}

// Wrap the app. Renders the public accept-invite page for its route, the login
// gate when session auth is active and unauthenticated, or the console.
export function AuthGate({ children }: { children: ReactNode }) {
  const route = useRoute();
  const { status } = useAuth();

  // The accept-invite page is public (the token is the bearer of authority) and
  // must render whether or not a session exists, so it is handled before the
  // session probe.
  const isAcceptInvite = route.tab === "accept-invite";

  useEffect(() => {
    if (!isAcceptInvite && status === "checking") void probeSession();
  }, [isAcceptInvite, status]);

  if (isAcceptInvite) return <AcceptInvitePage />;
  if (status === "checking") {
    return (
      <div className="auth-gate">
        <div className="auth-splash" role="status" aria-live="polite">
          <span className="auth-splash__spinner" aria-hidden="true" />
          <span className="auth-splash__text">Loading...</span>
        </div>
      </div>
    );
  }
  if (status === "unauthenticated") return <LoginPage />;
  if (status === "enroll_required") return <EnrollFlow />;
  return <>{children}</>;
}
