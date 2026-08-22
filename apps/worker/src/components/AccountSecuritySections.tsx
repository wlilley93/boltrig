import { useEffect, useState } from "react";
import type {
  PatView,
  MyOrganisationView,
  SessionView,
  TwoFactorEnrollBeginResponse,
  WorkspaceView,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../client";
import { copySensitiveText } from "../clipboard";

export function DeveloperTokens() {
  const [tokens, setTokens] = useState<PatView[]>([]);
  const [name, setName] = useState("");
  const [scope, setScope] = useState("");
  const [oneTimeSecret, setOneTimeSecret] = useState("");
  const [armedId, setArmedId] = useState<string | null>(null);
  const [message, setMessage] = useState("");

  function refresh() {
    void client.meTokens()
      .then((result) => setTokens(result.tokens))
      .catch(() => setMessage("Personal access tokens are unavailable."));
  }

  useEffect(refresh, []);

  async function mint() {
    try {
      const result = await client.mintToken({
        name: name.trim(),
        scope: scope.split(",").map((item) => item.trim()).filter(Boolean),
      });
      if (result.status !== "ok" || !result.secret) {
        setMessage(result.reason ?? "The token could not be minted.");
        return;
      }
      setOneTimeSecret(result.secret);
      setName("");
      setMessage("Copy this token now. Boltrig will not show it again.");
      refresh();
    } catch {
      setMessage("The token could not be minted. No token was created.");
    }
  }

  async function revoke(id: string) {
    if (armedId !== id) {
      setArmedId(id);
      return;
    }
    try {
      const result = await client.revokeToken(id);
      setMessage(result.status === "ok" ? "Token revoked." : result.reason ?? result.status);
      refresh();
    } catch {
      setMessage("The token could not be revoked. Nothing was changed.");
    } finally {
      setArmedId(null);
    }
  }

  async function copyToken() {
    setMessage(await copySensitiveText(oneTimeSecret)
      ? "Token copied to the clipboard. Keep it in an approved secret store."
      : "The token could not be copied. Select and copy it manually before dismissing it.");
  }

  return (
    <section className="settings-card">
      <p className="eyebrow">Developer access</p>
      <h2>Personal access tokens</h2>
      <input
        className="field-control"
        aria-label="Token name"
        placeholder="CLI on my laptop"
        value={name}
        onChange={(event) => setName(event.target.value)}
      />
      <input
        className="field-control"
        aria-label="Token scopes"
        placeholder="Optional comma-separated scopes"
        value={scope}
        onChange={(event) => setScope(event.target.value)}
      />
      <button className="primary-button" disabled={!name.trim()} onClick={() => void mint()}>
        Mint token
      </button>
      {oneTimeSecret && (
        <div className="approval-item" role="status">
          <strong>One-time token</strong>
          <code>{oneTimeSecret}</code>
          <div className="button-row">
            <button
              className="secondary-button"
              onClick={() => void copyToken()}
            >
              Copy
            </button>
            <button className="secondary-button" onClick={() => setOneTimeSecret("")}>
              Dismiss
            </button>
          </div>
        </div>
      )}
      <TokenRows tokens={tokens} armedId={armedId} onRevoke={revoke} />
      {message && <p className="notice" role="status">{message}</p>}
    </section>
  );
}

function TokenRows({
  tokens,
  armedId,
  onRevoke,
}: {
  tokens: PatView[];
  armedId: string | null;
  onRevoke(id: string): Promise<void>;
}) {
  return (
    <div className="data-list" aria-label="Personal access tokens">
      {tokens.map((token) => (
        <div className="data-row static" key={token.id}>
          <span className={`activity-dot ${token.revoked ? "failed" : "done"}`} />
          <span className="data-row-copy">
            <strong>{token.name}</strong>
            <small>{token.scope.join(", ") || "No scopes"} · {token.revoked ? "revoked" : "active"}</small>
          </span>
          {!token.revoked && (
            <button
              className={armedId === token.id ? "danger-button armed" : "danger-button"}
              onClick={() => void onRevoke(token.id)}
            >
              {armedId === token.id ? "Confirm revoke" : "Revoke"}
            </button>
          )}
        </div>
      ))}
    </div>
  );
}

export function SecuritySessions() {
  const [sessions, setSessions] = useState<SessionView[]>([]);
  const [armedId, setArmedId] = useState<string | null>(null);
  const [message, setMessage] = useState("");

  function refresh() {
    void client.meSessions()
      .then((result) => setSessions(result.sessions))
      .catch(() => setMessage("Session management requires a browser login."));
  }

  useEffect(refresh, []);

  async function revoke(id: string) {
    if (armedId !== id) {
      setArmedId(id);
      return;
    }
    try {
      const result = await client.revokeSession(id);
      setMessage(result.status === "ok" ? "Session revoked." : result.reason ?? result.status);
      refresh();
    } catch {
      setMessage("The session could not be revoked. Nothing was changed.");
    } finally {
      setArmedId(null);
    }
  }

  return (
    <section className="settings-card">
      <p className="eyebrow">Security</p>
      <h2>Signed-in sessions</h2>
      <div className="data-list" aria-label="Sessions">
        {sessions.map((session) => (
          <div className="data-row static" key={session.id}>
            <span className={`activity-dot ${session.revoked ? "failed" : "done"}`} />
            <span className="data-row-copy">
              <strong>{session.client || "Unknown client"}</strong>
              <small>{session.last_seen_at || session.created_at || "No timestamp"}</small>
            </span>
            {!session.revoked && (
              <button
                className={armedId === session.id ? "danger-button armed" : "danger-button"}
                onClick={() => void revoke(session.id)}
              >
                {armedId === session.id ? "Confirm revoke" : "Revoke"}
              </button>
            )}
          </div>
        ))}
      </div>
      {message && <p className="notice" role="status">{message}</p>}
    </section>
  );
}

export function TwoFactorSecurity() {
  const [enrollment, setEnrollment] = useState<TwoFactorEnrollBeginResponse | null>(null);
  const [verifyCode, setVerifyCode] = useState("");
  const [disableCode, setDisableCode] = useState("");
  const [disableArmed, setDisableArmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  async function beginEnrollment() {
    setBusy(true);
    setMessage("");
    try {
      const result = await client.twoFactorEnrollBegin();
      if (result.status !== "ok" || !result.secret || !result.otpauth_uri) {
        setMessage(result.reason ?? "Two-factor enrollment could not be started.");
        return;
      }
      setEnrollment(result);
      setMessage("Add the secret to your authenticator, save the recovery codes, then verify one code.");
    } catch {
      setMessage("Two-factor enrollment is unavailable.");
    } finally {
      setBusy(false);
    }
  }

  async function verifyEnrollment() {
    setBusy(true);
    setMessage("");
    try {
      const result = await client.twoFactorVerifyEnroll({ code: verifyCode.trim() });
      setVerifyCode("");
      setMessage(result.status === "ok"
        ? `Two-factor authentication is active. ${result.recovery_codes_remaining ?? enrollment?.recovery_codes?.length ?? 0} recovery codes remain.`
        : result.reason ?? "The code was not accepted.");
    } catch {
      setMessage("The code was not accepted.");
    } finally {
      setBusy(false);
    }
  }

  async function disable() {
    if (!disableArmed) {
      setDisableArmed(true);
      setMessage("Enter a current authenticator or recovery code, then confirm once more.");
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      const result = await client.twoFactorDisable(disableCode.trim());
      if (result.status === "ok") {
        setEnrollment(null);
        setDisableCode("");
        setDisableArmed(false);
        setMessage("Two-factor authentication was disabled. Organisation policy may require immediate re-enrollment.");
      } else {
        setMessage(result.reason ?? "Two-factor authentication was not disabled.");
      }
    } catch {
      setMessage("The factor could not be disabled. No security setting was changed.");
    } finally {
      setBusy(false);
    }
  }

  async function copyEnrollmentSecret() {
    setMessage(await copySensitiveText(enrollment?.secret ?? "")
      ? "Authenticator secret copied to the clipboard."
      : "The authenticator secret could not be copied. Select and copy it manually before dismissing it.");
  }

  async function copyRecoveryCodes() {
    setMessage(await copySensitiveText(enrollment?.recovery_codes?.join("\n") ?? "")
      ? "Recovery codes copied to the clipboard. Store every code securely."
      : "The recovery codes could not be copied. Select and copy them manually before dismissing them.");
  }

  return (
    <section className="settings-card">
      <p className="eyebrow">Two-factor authentication</p>
      <h2>Authenticator and recovery codes</h2>
      <p>Enrollment secrets and recovery codes are shown once. Boltrig stores only sealed factor material and recovery-code hashes.</p>
      {!enrollment ? (
        <button className="primary-button" disabled={busy} onClick={() => void beginEnrollment()}>
          {busy ? "Starting…" : "Start enrollment"}
        </button>
      ) : (
        <div className="secret-once" role="status">
          <strong>One-time enrollment details</strong>
          <p>Authenticator secret</p>
          <code>{enrollment.secret}</code>
          <button className="secondary-button" onClick={() => void copyEnrollmentSecret()}>Copy secret</button>
          <details>
            <summary>Manual authenticator URI</summary>
            <code>{enrollment.otpauth_uri}</code>
          </details>
          <p>Recovery codes — save every code before dismissing.</p>
          <code>{enrollment.recovery_codes?.join("\n")}</code>
          <div className="button-row">
            <button className="secondary-button" onClick={() => void copyRecoveryCodes()}>Copy recovery codes</button>
            <button className="secondary-button" onClick={() => setEnrollment(null)}>Dismiss details</button>
          </div>
          <label><span>Authenticator code</span><input className="field-control" inputMode="numeric" autoComplete="one-time-code" value={verifyCode} onChange={(event) => setVerifyCode(event.target.value)} /></label>
          <button className="primary-button" disabled={busy || !verifyCode.trim()} onClick={() => void verifyEnrollment()}>Verify and enable</button>
        </div>
      )}
      <div className="detail-section">
        <label><span>Current authenticator or recovery code</span><input className="field-control" type="password" autoComplete="one-time-code" value={disableCode} onChange={(event) => setDisableCode(event.target.value)} /></label>
        <button
          className={disableArmed ? "danger-button armed" : "danger-button"}
          disabled={busy || !disableCode.trim()}
          onClick={() => void disable()}
        >
          {disableArmed ? "Confirm disable 2FA" : "Disable 2FA"}
        </button>
      </div>
      {message && <p className="notice" role="status">{message}</p>}
    </section>
  );
}

export function PasswordSecurity() {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  async function change(event: React.FormEvent) {
    event.preventDefault();
    if (newPassword !== confirmPassword) {
      setMessage("The new passwords do not match.");
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      const result = await client.changePassword({
        current_password: currentPassword,
        new_password: newPassword,
      });
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setMessage(result.status === "ok"
        ? "Password changed."
        : result.reason ?? "The password was not changed.");
    } catch {
      setMessage("The password was not changed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="settings-card author-form" onSubmit={(event) => void change(event)}>
      <p className="eyebrow">Password</p>
      <h2>Change password</h2>
      <label><span>Current password</span><input className="field-control" type="password" autoComplete="current-password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} required /></label>
      <label><span>New password</span><input className="field-control" type="password" autoComplete="new-password" minLength={12} value={newPassword} onChange={(event) => setNewPassword(event.target.value)} required /></label>
      <label><span>Confirm new password</span><input className="field-control" type="password" autoComplete="new-password" minLength={12} value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} required /></label>
      <button className="primary-button" disabled={busy || !currentPassword || !newPassword || !confirmPassword}>{busy ? "Changing…" : "Change password"}</button>
      {message && <p className="notice" role="status">{message}</p>}
    </form>
  );
}

