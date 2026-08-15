import { useEffect, useState } from "react";
import type { ConnectionsResponse } from "@wlilley93/boltrig-web-sdk";

import { client } from "../client";

export function ConnectionInstructions() {
  const [instructions, setInstructions] = useState<ConnectionsResponse | null>(null);
  const [message, setMessage] = useState("");

  useEffect(() => {
    void client.meConnections()
      .then(setInstructions)
      .catch(() => setMessage("Developer connection instructions are unavailable."));
  }, []);

  return (
    <section className="settings-card">
      <p className="eyebrow">Developer connections</p>
      <h2>Connect a client to Boltrig</h2>
      {!instructions ? (
        <p className="muted">Loading connections…</p>
      ) : (
        <>
          <dl className="fact-grid">
            <div><dt>REST base</dt><dd>{instructions.rest_base}</dd></div>
            <div><dt>MCP endpoint</dt><dd>{instructions.mcp_endpoint}</dd></div>
          </dl>
          <p>Authenticate with a personal access token. Token values are shown only when minted.</p>
          <Instruction
            label="Claude Code"
            value={safeInstruction(instructions.snippets.claude_code)}
          />
          <Instruction label="cURL" value={safeInstruction(instructions.snippets.curl)} />
          <p className="muted small">{instructions.note}</p>
        </>
      )}
      {message && <p className="notice" role="status">{message}</p>}
    </section>
  );
}

function Instruction({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }
  return (
    <div className="connection-instruction">
      <div><span className="eyebrow">{label}</span></div>
      <code>{value}</code>
      <button className="secondary-button" onClick={() => void copy()}>
        {copied ? "Copied" : "Copy"}
      </button>
    </div>
  );
}

function safeInstruction(value: string): string {
  return value
    .replace(/Bearer\s+(?!<)[^\s'"]+/gi, "Bearer <PAT>")
    .replace(/(x-api-key\s*[:=]\s*)(?!<)[^\s'"]+/gi, "$1<PAT>");
}
