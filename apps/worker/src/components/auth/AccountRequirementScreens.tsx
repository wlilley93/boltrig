import { useEffect, useRef, useState } from "react";

import { client, rememberSessionCsrf } from "../../client";
import { AuthCard } from "./AuthShell";

export function ChallengeScreen({
  token,
  onBack,
  onDone,
}: {
  token: string;
  onBack(): void;
  onDone(): void;
}) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await client.twoFactorChallenge({ challenge_token: token, code: code.trim() });
      if (result.status === "ok") {
        rememberSessionCsrf(result.csrf_token);
        onDone();
      }
      else setError(result.reason ?? "That verification code was not accepted.");
    } catch {
      setError("Could not verify the code.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard title="Verify it’s you" lead="Enter an authenticator or recovery code.">
      <form className="auth-form" onSubmit={submit}>
        <label><span>Verification code</span><input inputMode="numeric" autoComplete="one-time-code" autoFocus value={code} onChange={(event) => setCode(event.target.value)} /></label>
        {error && <p className="auth-error" role="alert">{error}</p>}
        <div className="auth-actions"><button type="button" className="secondary-button" onClick={onBack}>Back</button><button className="primary-button" disabled={busy || !code.trim()}>{busy ? "Verifying…" : "Verify"}</button></div>
      </form>
    </AuthCard>
  );
}

export function PasswordChangeScreen({ onDone }: { onDone(): void }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (next !== confirm) return setError("The new passwords do not match.");
    setBusy(true);
    setError("");
    try {
      const result = await client.changePassword({
        current_password: current,
        new_password: next,
      });
      if (result.status === "ok") onDone();
      else setError(result.reason ?? "The password was not changed.");
    } catch {
      setError("Could not change the password.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard title="Choose a new password" lead="Replace the temporary provisioning credential before continuing.">
      <form className="auth-form" onSubmit={submit}>
        <label><span>Current password</span><input type="password" autoComplete="current-password" value={current} onChange={(event) => setCurrent(event.target.value)} /></label>
        <label><span>New password</span><input type="password" autoComplete="new-password" value={next} onChange={(event) => setNext(event.target.value)} /></label>
        <label><span>Confirm new password</span><input type="password" autoComplete="new-password" value={confirm} onChange={(event) => setConfirm(event.target.value)} /></label>
        {error && <p className="auth-error" role="alert">{error}</p>}
        <button className="primary-button" disabled={busy || !current || !next || !confirm}>{busy ? "Changing…" : "Change password"}</button>
      </form>
    </AuthCard>
  );
}

export function EnrollmentRequiredScreen({ onDone }: { onDone(): void }) {
  const started = useRef(false);
  const [secret, setSecret] = useState("");
  const [uri, setUri] = useState("");
  const [recoveryCodes, setRecoveryCodes] = useState<string[]>([]);
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void client.twoFactorEnrollBegin()
      .then((result) => {
        if (result.status !== "ok") {
          setError(result.reason ?? "Two-factor enrollment is unavailable.");
          return;
        }
        setSecret(result.secret ?? "");
        setUri(result.otpauth_uri ?? "");
        setRecoveryCodes(result.recovery_codes ?? []);
      })
      .catch(() => setError("Two-factor enrollment is unavailable."))
      .finally(() => setBusy(false));
  }, []);

  async function verify(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await client.twoFactorVerifyEnroll({ code: code.trim() });
      if (result.status === "ok") onDone();
      else setError(result.reason ?? "That authenticator code was not accepted.");
    } catch {
      setError("Could not finish two-factor enrollment.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard title="Two-factor setup required" lead="Your organisation requires an authenticator before Worker can open.">
      {busy && !secret
        ? <div className="auth-splash" role="status"><span className="auth-spinner" />Preparing enrollment…</div>
        : <EnrollmentForm
            busy={busy}
            code={code}
            error={error}
            recoveryCodes={recoveryCodes}
            secret={secret}
            setCode={setCode}
            uri={uri}
            verify={verify}
          />}
    </AuthCard>
  );
}

interface EnrollmentFormProps {
  busy: boolean;
  code: string;
  error: string;
  recoveryCodes: string[];
  secret: string;
  setCode(value: string): void;
  uri: string;
  verify(event: React.FormEvent): void;
}

function EnrollmentForm(props: EnrollmentFormProps) {
  return (
    <form className="auth-form" onSubmit={props.verify}>
      <div className="auth-secret">
        <span>Authenticator secret</span>
        <code>{props.secret || "Unavailable"}</code>
        {props.uri && <small>Add this secret manually in your authenticator. The full otpauth URI is available below.</small>}
        {props.uri && <details><summary>otpauth URI</summary><code>{props.uri}</code></details>}
      </div>
      {props.recoveryCodes.length > 0 && (
        <div className="recovery-codes">
          <strong>Save these recovery codes now</strong>
          <p>They are shown once. Store them outside Boltrig.</p>
          <code>{props.recoveryCodes.join("\n")}</code>
        </div>
      )}
      <label><span>Authenticator code</span><input inputMode="numeric" autoComplete="one-time-code" value={props.code} onChange={(event) => props.setCode(event.target.value)} /></label>
      {props.error && <p className="auth-error" role="alert">{props.error}</p>}
      <button className="primary-button" disabled={props.busy || !props.secret || !props.code.trim()}>{props.busy ? "Verifying…" : "Finish setup"}</button>
    </form>
  );
}
