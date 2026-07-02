// Settings / Developer & Connections: mint personal access tokens (SEC-34,
// show-once secret), list them, and the connection details card.
// Mechanical extraction of DeveloperConnections from SettingsPanel.tsx (Beat 5).

import { useState } from "react";

import { api } from "../../api/client";
import type { MintTokenResponse } from "../../api/types";
import { useFetch } from "../../useFetch";
import { csvToList, errText } from "../shared";
import { PageIntro } from "../ux";
import { TokenList } from "./shared";

function copyText(text: string): void {
  void navigator.clipboard?.writeText(text).catch(() => undefined);
}

function CopyRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="copy-row">
      <span className="copy-row__label muted">{label}</span>
      <code className="copy-row__value">{value}</code>
      <button
        className="btn"
        aria-label={`Copy ${label}`}
        onClick={() => copyText(value)}
      >
        Copy
      </button>
    </div>
  );
}

function DeveloperConnections() {
  const connections = useFetch(() => api.meConnections(), []);

  const [name, setName] = useState("");
  const [scope, setScope] = useState("");
  const [ttl, setTtl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [minted, setMinted] = useState<MintTokenResponse | null>(null);
  const [bump, setBump] = useState(0);

  async function mint() {
    if (!name.trim()) {
      setError("A token name is required.");
      return;
    }
    setBusy(true);
    setError(null);
    setMinted(null);
    try {
      const ttlDays = ttl.trim() ? Number(ttl.trim()) : undefined;
      if (ttlDays !== undefined && Number.isNaN(ttlDays)) {
        setError("ttl_days must be a number.");
        setBusy(false);
        return;
      }
      const res = await api.mintToken({
        name: name.trim(),
        scope: scope.trim() ? csvToList(scope) : undefined,
        ttl_days: ttlDays,
      });
      if (res.status === "ok") {
        setMinted(res);
        setName("");
        setScope("");
        setTtl("");
        setBump((n) => n + 1); // force the token list to reload
      } else {
        setError(res.reason ?? "mint rejected");
      }
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  const conn = connections.data;

  return (
    <div className="cols">
      <div className="stack">
        <div className="form">
          <div className="form__title">Mint a personal access token</div>
          <p className="muted">
            A token is scoped to a subset of your own grants and re-checked on
            every use, so it can never escalate (SEC-34).
          </p>
          <div className="form__grid">
            <label className="field">
              <span>name</span>
              <input value={name} onChange={(e) => setName(e.target.value)} />
            </label>
            <label className="field">
              <span>scope (comma list, optional)</span>
              <input
                value={scope}
                placeholder="ticket.read, ticket.comment"
                onChange={(e) => setScope(e.target.value)}
              />
            </label>
            <label className="field">
              <span>ttl_days (optional)</span>
              <input
                value={ttl}
                placeholder="30"
                onChange={(e) => setTtl(e.target.value)}
              />
            </label>
          </div>
          <div className="form__actions">
            <button
              className="btn btn--primary"
              disabled={busy}
              onClick={() => void mint()}
            >
              {busy ? "..." : "Mint token"}
            </button>
            {error && <span className="error">{error}</span>}
          </div>

          {minted && minted.secret && (
            <div className="notice warn secret-box">
              <p className="warn">
                <strong>Copy your token now.</strong> This is the only time the
                secret is shown - it is never stored in the clear and cannot be
                retrieved again.
              </p>
              <div className="copy-row">
                <code className="copy-row__value secret-box__value">
                  {minted.secret}
                </code>
                <button
                  className="btn btn--primary"
                  aria-label="Copy token secret"
                  onClick={() => copyText(minted.secret ?? "")}
                >
                  Copy
                </button>
              </div>
              <p className="muted">
                token <code>{minted.name}</code> ({minted.id}); expires{" "}
                {minted.expires_at ?? "-"}
              </p>
            </div>
          )}
        </div>

        <TokenList bump={bump} />
      </div>

      <div className="list-card">
        <div className="list-card__head">
          <h3>Connection details</h3>
          <button className="btn" onClick={() => connections.reload()}>
            Refresh
          </button>
        </div>
        <div className="list-card__body">
          {connections.loading && !connections.data && (
            <p className="muted">Loading...</p>
          )}
          {connections.error && (
            <p className="error">Failed to load: {connections.error}</p>
          )}
          {conn && (
            <>
              <CopyRow label="MCP endpoint" value={conn.mcp_endpoint} />
              <CopyRow label="REST base" value={conn.rest_base} />
              <CopyRow label="auth" value={conn.auth} />
              <p className="muted">Claude Code</p>
              <CopyRow label="claude mcp add" value={conn.snippets.claude_code} />
              <p className="muted">curl</p>
              <CopyRow label="curl" value={conn.snippets.curl} />
              <p className="muted">{conn.note}</p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export function DeveloperSlide() {
  return (
    <section className="panel">
      <PageIntro
        title="Developer & Connections"
        lead="Personal access tokens and how to connect clients."
      />
      <DeveloperConnections />
    </section>
  );
}
