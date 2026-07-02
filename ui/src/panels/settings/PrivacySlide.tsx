// Settings / Privacy & My Data: export the caller's own data (SET-60) and
// manage (soft-close) their conversations.
// Mechanical extraction of PrivacyData from SettingsPanel.tsx (Beat 5).

import { useState } from "react";

import { api } from "../../api/client";
import { CodeBlock, errText, prettyJson } from "../shared";
import { PageIntro } from "../ux";

function downloadJson(filename: string, value: unknown): void {
  const blob = new Blob([prettyJson(value)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function PrivacyData() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<Awaited<
    ReturnType<typeof api.meExport>
  > | null>(null);

  async function load() {
    setBusy(true);
    setError(null);
    try {
      setData(await api.meExport());
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    if (
      !window.confirm("Delete this conversation? This closes it for your account.")
    ) {
      return;
    }
    setError(null);
    try {
      const res = await api.deleteMyConversation(id);
      if (res.status === "ok") void load();
      else setError(res.reason ?? "delete rejected");
    } catch (err) {
      setError(errText(err));
    }
  }

  const conversations = data?.conversations ?? [];

  return (
    <div className="cols">
      <div className="form">
        <div className="form__title">Export my data</div>
        <p className="muted">
          A copy of your own conversations, owned work items and settings
          (SET-60). Your data only - nothing from other users.
        </p>
        <div className="form__actions">
          <button
            className="btn btn--primary"
            disabled={busy}
            onClick={() => void load()}
          >
            {busy ? "..." : "Load export"}
          </button>
          {data && (
            <button
              className="btn"
              onClick={() => downloadJson("boltrig-export.json", data)}
            >
              Download JSON
            </button>
          )}
          {error && <span className="error">{error}</span>}
        </div>
        {data && <CodeBlock value={data} />}
      </div>

      <div className="list-card">
        <div className="list-card__head">
          <h3>My conversations</h3>
          <span className="muted">{conversations.length}</span>
        </div>
        <div className="list-card__body">
          {!data && (
            <p className="muted">Load the export to list your conversations.</p>
          )}
          {data && conversations.length === 0 && (
            <p className="muted">No conversations.</p>
          )}
          {conversations.map((c) => (
            <div className="row-line" key={c.id}>
              <div>
                <span>{c.title || "(untitled)"}</span>
                <div className="muted">
                  <code>{c.id}</code> - {c.status}
                </div>
              </div>
              <button className="btn" onClick={() => void remove(c.id)}>
                Delete
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export function PrivacySlide() {
  return (
    <section className="panel">
      <PageIntro
        title="Privacy & My Data"
        lead="Export your data; manage your conversations."
      />
      <PrivacyData />
    </section>
  );
}
