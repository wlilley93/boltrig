import { useEffect, useRef, useState } from "react";

import { configuredApiOrigin } from "../apiOrigin";
import { characterFromSettings, saveCharacterLocal } from "../character";
import { client } from "../client";
import { clearDesktopSession, isDesktop } from "../desktop";
import { BoltrigApiError } from "@wlilley93/boltrig-web-sdk";

type GateState =
  | "checking"
  | "authenticated"
  | "unauthenticated"
  | "password_change_required"
  | "enrollment_required";
type RecoveryFlow = "none" | "request" | "confirm";

function recoveryFlowFromHash(): RecoveryFlow {
  if (window.location.hash.startsWith("#/reset-password")) return "confirm";
  if (window.location.hash.startsWith("#/forgot-password")) return "request";
  return "none";
}

function acceptingInviteFromHash(): boolean {
  return window.location.hash.startsWith("#/accept-invite");
}

export function AuthGate({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<GateState>("checking");
  const [challenge, setChallenge] = useState<string | null>(null);
  const [recoveryFlow, setRecoveryFlow] = useState<RecoveryFlow>(recoveryFlowFromHash);
  const [recoveryEmail, setRecoveryEmail] = useState("");
  const [acceptingInvite, setAcceptingInvite] = useState(acceptingInviteFromHash);

  useEffect(() => {
    const onHashChange = () => {
      setRecoveryFlow(recoveryFlowFromHash());
      setAcceptingInvite(acceptingInviteFromHash());
    };
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  useEffect(() => {
    if (acceptingInvite || recoveryFlow !== "none") return;
    void client.meSettings()
      .then((result) => {
        // The authentication read already owns the authoritative settings
        // snapshot. Apply the selected Stage character before private UI mounts
        // so a returning session cannot flash the locally cached body first.
        saveCharacterLocal(characterFromSettings(result.settings));
        setState("authenticated");
      })
      .catch((reason) => {
        if (reason instanceof BoltrigApiError && reason.status === 403) {
          const detail = detailOf(reason.body);
          if (detail === "password_change_required") return setState("password_change_required");
          if (detail === "two_factor_enrollment_required") return setState("enrollment_required");
        }
        setState("unauthenticated");
      });
  }, [acceptingInvite, recoveryFlow]);

  useEffect(() => {
    if (state !== "authenticated") return;
    let active = true;
    const rotate = () => {
      void client.refreshSession().catch((reason) => {
        if (active && reason instanceof BoltrigApiError && reason.status === 401) {
          // Another tab may have rotated the shared cookie while this request
          // was in flight. Re-resolve the session before treating it as gone.
          void client.meSettings().catch((check) => {
            if (active && check instanceof BoltrigApiError && check.status === 401) {
              setState("unauthenticated");
            }
          });
        }
      });
    };
    const timer = window.setInterval(rotate, 4 * 60 * 60 * 1000);
    const onVisibility = () => {
      if (document.visibilityState === "visible") rotate();
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      active = false;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [state]);

  const backToSignIn = () => {
    window.location.hash = "#/chat";
    setRecoveryFlow("none");
    setAcceptingInvite(false);
    setState("unauthenticated");
  };
  // A desktop build packaged without VITE_API_BASE would send every request to
  // its own tauri://localhost webview, where no kernel exists. Name that here
  // rather than letting sign-in, chat and voice each fail as network errors.
  if (isDesktop && !configuredApiOrigin()) return <DesktopServerMissing />;
  if (acceptingInvite) return <AcceptInvite onDone={backToSignIn} />;
  if (recoveryFlow === "request") {
    return <RequestPasswordReset initialEmail={recoveryEmail} onDone={backToSignIn} />;
  }
  if (recoveryFlow === "confirm") {
    return <ResetPassword onDone={backToSignIn} />;
  }
  if (state === "checking") return <AuthSplash />;
  if (state === "password_change_required") return <PasswordChange onDone={() => setState("authenticated")} />;
  if (state === "enrollment_required") return <EnrollmentRequired onDone={() => setState("authenticated")} />;
  if (state === "unauthenticated") {
    return challenge
      ? <Challenge token={challenge} onBack={() => setChallenge(null)} onDone={() => setState("authenticated")} />
      : <Login
          onChallenge={setChallenge}
          onState={setState}
          onForgot={(email) => {
            setRecoveryEmail(email);
            window.location.hash = "#/forgot-password";
            setRecoveryFlow("request");
          }}
        />;
  }
  return <>{children}</>;
}

function AuthSplash() {
  return (
    <main className="auth-surface">
      <div className="auth-splash" role="status"><span className="auth-spinner" /><span>Opening Boltrig Worker…</span></div>
    </main>
  );
}

function DesktopServerMissing() {
  return (
    <AuthCard
      title="No Boltrig server configured"
      lead="This desktop build was packaged without a Boltrig API origin."
    >
      <div className="auth-handoff">
        <p role="alert" className="auth-error">
          Rebuild the desktop app with VITE_API_BASE set to the Boltrig origin
          this install should use. Without it the app can only reach its own
          window, so sign-in, chat and voice have nothing to talk to.
        </p>
      </div>
    </AuthCard>
  );
}

function Login({
  onChallenge,
  onState,
  onForgot,
}: {
  onChallenge(token: string): void;
  onState(state: GateState): void;
  onForgot(email: string): void;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [localResetArmed, setLocalResetArmed] = useState(false);
  const [localResetBusy, setLocalResetBusy] = useState(false);
  const [localResetMessage, setLocalResetMessage] = useState("");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const result = await client.login({ email: email.trim(), password });
      if (result.status === "ok") return onState("authenticated");
      if (result.status === "2fa_required" && result.challenge_token) return onChallenge(result.challenge_token);
      if (result.status === "password_change_required") return onState("password_change_required");
      if (result.status === "2fa_enrollment_required") return onState("enrollment_required");
      setError(result.reason ?? "Incorrect email or password.");
    } catch {
      setError("Could not reach Boltrig. Try again.");
    } finally {
      setBusy(false);
    }
  }

  async function resetLocalEnrollment() {
    if (!localResetArmed) {
      setLocalResetArmed(true);
      setLocalResetMessage(
        "This removes the device-agent identity and local root bindings from this computer. It does not revoke the server device or change your browser sign-in.",
      );
      return;
    }
    if (localResetBusy) return;
    setLocalResetBusy(true);
    setLocalResetMessage("");
    try {
      await clearDesktopSession();
      setLocalResetArmed(false);
      setLocalResetMessage(
        "Local device enrollment was removed. Your browser sign-in was not changed.",
      );
    } catch {
      setLocalResetMessage(
        "Local device enrollment could not be removed from the OS keychain. It is safe to retry.",
      );
    } finally {
      setLocalResetBusy(false);
    }
  }

  return (
    <AuthCard title="Welcome back" lead={isDesktop ? "Sign in to this Worker desktop session." : "Sign in to your Boltrig workspace."}>
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
      {isDesktop && (
        <div className="auth-handoff">
          <p>Having trouble with this desktop’s local device enrollment?</p>
          <button
            type="button"
            className={localResetArmed ? "danger-button armed" : "secondary-button"}
            disabled={localResetBusy}
            onClick={() => void resetLocalEnrollment()}
          >
            {localResetBusy
              ? "Removing local enrollment…"
              : localResetArmed
                ? "Confirm local enrollment reset"
                : "Reset local device enrollment"}
          </button>
          {localResetMessage && (
            <p
              className="muted small"
              role={localResetArmed ? "alert" : "status"}
            >
              {localResetMessage}
            </p>
          )}
        </div>
      )}
      <p className="auth-foot">Boltrig is invite only. Permanent provider and integration credentials never enter this client.</p>
    </AuthCard>
  );
}

function RequestPasswordReset({
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

  if (sent) {
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
  return (
    <AuthCard title="Reset your password" lead="Enter the email used for your Boltrig account.">
      <form className="auth-form" onSubmit={submit}>
        <label>
          <span>Email</span>
          <input
            type="email"
            autoComplete="username"
            autoFocus
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
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

function ResetPassword({ onDone }: { onDone(): void }) {
  const token = new URLSearchParams(window.location.hash.split("?")[1] ?? "").get("token") ?? "";
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
      const result = await client.confirmPasswordReset({
        token,
        new_password: password,
      });
      if (result.status === "ok") setComplete(true);
      else setError(result.reason ?? "This reset link could not be used.");
    } catch {
      setError("Could not reset the password.");
    } finally {
      setBusy(false);
    }
  }

  if (complete) {
    return (
      <AuthCard title="Password reset" lead="Your new password is ready to use.">
        <div className="auth-handoff">
          <p>All existing browser sessions have been signed out.</p>
          <button className="primary-button" onClick={onDone}>Go to sign in</button>
        </div>
      </AuthCard>
    );
  }
  if (!token) {
    return (
      <AuthCard title="Reset your password" lead="This reset link is incomplete.">
        <div className="auth-handoff">
          <p className="auth-error">The reset token is missing. Request a new link.</p>
          <button className="secondary-button" onClick={onDone}>Back to sign in</button>
        </div>
      </AuthCard>
    );
  }
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

function Challenge({ token, onBack, onDone }: { token: string; onBack(): void; onDone(): void }) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await client.twoFactorChallenge({ challenge_token: token, code: code.trim() });
      if (result.status === "ok") onDone();
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

function PasswordChange({ onDone }: { onDone(): void }) {
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
      const result = await client.changePassword({ current_password: current, new_password: next });
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

function EnrollmentRequired({ onDone }: { onDone(): void }) {
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
        if (result.status !== "ok") setError(result.reason ?? "Two-factor enrollment is unavailable.");
        else {
          setSecret(result.secret ?? "");
          setUri(result.otpauth_uri ?? "");
          setRecoveryCodes(result.recovery_codes ?? []);
        }
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
      {busy && !secret ? <div className="auth-splash" role="status"><span className="auth-spinner" />Preparing enrollment…</div> : (
        <form className="auth-form" onSubmit={verify}>
          <div className="auth-secret">
            <span>Authenticator secret</span>
            <code>{secret || "Unavailable"}</code>
            {uri && <small>Add this secret manually in your authenticator. The full otpauth URI is available below.</small>}
            {uri && <details><summary>otpauth URI</summary><code>{uri}</code></details>}
          </div>
          {recoveryCodes.length > 0 && (
            <div className="recovery-codes">
              <strong>Save these recovery codes now</strong>
              <p>They are shown once. Store them outside Boltrig.</p>
              <code>{recoveryCodes.join("\n")}</code>
            </div>
          )}
          <label><span>Authenticator code</span><input inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(event) => setCode(event.target.value)} /></label>
          {error && <p className="auth-error" role="alert">{error}</p>}
          <button className="primary-button" disabled={busy || !secret || !code.trim()}>{busy ? "Verifying…" : "Finish setup"}</button>
        </form>
      )}
    </AuthCard>
  );
}

function AcceptInvite({ onDone }: { onDone(): void }) {
  const token = new URLSearchParams(window.location.hash.split("?")[1] ?? "").get("token") ?? "";
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

  if (email !== null) {
    return (
      <AuthCard title="Account created" lead={email ? `Your password is set for ${email}.` : "Your password is set."}>
        <div className="auth-handoff"><p>You can now sign in with the password you just chose.</p><button className="primary-button" onClick={onDone}>Go to sign in</button></div>
      </AuthCard>
    );
  }
  return (
    <AuthCard title="Accept your invitation" lead="Choose a password to finish creating your Boltrig account.">
      {!token ? <div className="auth-handoff"><p className="auth-error">This invitation link is missing its token. Ask an administrator to resend it.</p><button className="secondary-button" onClick={onDone}>Back to sign in</button></div> : (
        <form className="auth-form" onSubmit={submit}>
          <label><span>New password</span><input type="password" autoComplete="new-password" autoFocus value={password} onChange={(event) => setPassword(event.target.value)} /></label>
          <label><span>Confirm password</span><input type="password" autoComplete="new-password" value={confirm} onChange={(event) => setConfirm(event.target.value)} /></label>
          {password.length > 0 && password.length < 12 && <p className="auth-error">Use at least 12 characters.</p>}
          {confirm.length > 0 && password !== confirm && <p className="auth-error">The passwords do not match.</p>}
          {error && <p className="auth-error" role="alert">{error}</p>}
          <button className="primary-button" disabled={busy || password.length < 12 || password !== confirm}>{busy ? "Creating…" : "Set password"}</button>
        </form>
      )}
    </AuthCard>
  );
}

function AuthCard({ title, lead, children }: { title: string; lead: string; children: React.ReactNode }) {
  return (
    <main className="auth-surface">
      <section className="auth-card">
        <div className="auth-brand"><span className="bolt-mark">ϟ</span><span>Boltrig Worker</span></div>
        <p className="eyebrow">Governed workspace</p>
        <h1>{title}</h1>
        <p className="auth-lead">{lead}</p>
        {children}
      </section>
    </main>
  );
}

function detailOf(body: unknown): string | null {
  return body && typeof body === "object" && "detail" in body
    ? String((body as { detail?: unknown }).detail ?? "")
    : null;
}
