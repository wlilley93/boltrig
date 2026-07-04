import { useEffect, useState } from "react";

import { api } from "@/api/client";
import { markAuthenticated } from "@/auth";
import { navigate } from "@/router";
import { AuthShell } from "@/panels/AuthGate/AuthShell";

type EnrollBegin = {
  secret: string;
  otpauthUri: string;
  recoveryCodes: string[];
};

type EnrollSetupProps = {
  begin: EnrollBegin;
  code: string;
  setCode: (value: string) => void;
  busy: boolean;
  error: string | null;
  onSubmit: (e: React.FormEvent) => void;
};

function EnrollSetup({
  begin,
  code,
  setCode,
  busy,
  error,
  onSubmit,
}: EnrollSetupProps) {
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
      <form className="auth-form" onSubmit={onSubmit}>
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

function EnrollLoading() {
  return (
    <AuthShell title="Two-factor setup" lead="Preparing your authenticator setup...">
      <div className="auth-splash" role="status" aria-live="polite">
        <span className="auth-splash__spinner" aria-hidden="true" />
        <span className="auth-splash__text">Loading...</span>
      </div>
    </AuthShell>
  );
}

function EnrollError({ loadError }: { loadError: string }) {
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

export function EnrollFlow() {
  const [begin, setBegin] = useState<EnrollBegin | null>(null);
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

  if (loadError) return <EnrollError loadError={loadError} />;
  if (!begin) return <EnrollLoading />;

  return (
    <EnrollSetup
      begin={begin}
      code={code}
      setCode={setCode}
      busy={busy}
      error={error}
      onSubmit={confirm}
    />
  );
}
