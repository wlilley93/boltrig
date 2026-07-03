// Settings / Developer & Connections: mint personal access tokens (SEC-34,
// show-once secret), list them, and the connection details card.
// Mechanical extraction of DeveloperConnections from SettingsPanel.tsx (Beat 5).

import { useState } from "react";

import { api } from "../../api/client";
import type { MintTokenResponse } from "../../api/types";
import { useFetch } from "../../useFetch";
import { csvToList, errText } from "../shared";
import {
  Field,
  FetchError,
  PageIntro,
  Select,
  TTL_OPTIONS,
  ttlDaysFromSelection,
} from "../ux";
import { SecretOnce, Skeleton } from "../uxFlow";
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
  const [ttl, setTtl] = useState("30");
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
      const res = await api.mintToken({
        name: name.trim(),
        scope: scope.trim() ? csvToList(scope) : undefined,
        ttl_days: ttlDaysFromSelection(ttl),
      });
      if (res.status === "ok") {
        setMinted(res);
        setName("");
        setScope("");
        setTtl("30");
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
            <Field label="Name" required example="ci-bot">
              <input value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <Field
              label="Scope"
              hint="Comma-separated grants (optional). Defaults to your own grants."
              example="ticket.read, ticket.comment"
            >
              <input
                value={scope}
                placeholder="ticket.read, ticket.comment"
                onChange={(e) => setScope(e.target.value)}
              />
            </Field>
            <Field label="Expires in (days)" hint="How long this token stays valid.">
              <Select
                value={ttl}
                ariaLabel="Token expiry"
                onChange={setTtl}
                options={TTL_OPTIONS}
              />
            </Field>
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
            <SecretOnce
              secret={minted.secret}
              title="Copy your token now."
              body="This is the only time the secret is shown. It is never stored in the clear and cannot be retrieved again."
              meta={
                <p className="muted">
                  token <code>{minted.name}</code> ({minted.id}); expires{" "}
                  {minted.expires_at ?? "-"}
                </p>
              }
              onDone={() => setMinted(null)}
            />
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
            <Skeleton variant="rows" count={5} />
          )}
          <FetchError
            error={connections.error}
            status={connections.errorStatus}
            onRetry={connections.reload}
          />
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
