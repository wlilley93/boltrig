// Settings / Privacy & My Data: export the caller's own data (SET-60) and
// manage (soft-close) their conversations.
// Mechanical extraction of PrivacyData from SettingsPanel.tsx (Beat 5).

import { useState } from "react";

import { api } from "../../api/client";
import { navigate } from "../../router";
import { CodeBlock, errText, prettyJson } from "../shared";
import { EmptyState, PageIntro } from "../ux";
import { ArmConfirm } from "../uxFlow";

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

  // Throws on a rejected delete so the row's ArmConfirm renders the reason.
  async function remove(id: string) {
    const res = await api.deleteMyConversation(id);
    if (res.status !== "ok") {
      throw new Error(res.reason ?? "delete rejected");
    }
    void load();
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
            <EmptyState
              title="No conversations"
              body="Start one in Chat."
              action={
                <button className="btn" onClick={() => navigate("/chat")}>
                  Open Chat
                </button>
              }
            />
          )}
          {conversations.map((c) => (
            <div className="row-line" key={c.id}>
              <div>
                <span>{c.title || "(untitled)"}</span>
                <div className="muted">
                  <code>{c.id}</code> - {c.status}
                </div>
              </div>
              <ArmConfirm
                label="Delete"
                armLabel={
                  <>
                    Delete "{c.title || "(untitled)"}"? This closes it for your
                    account; retention rules govern the underlying records.
                  </>
                }
                confirmLabel="Confirm delete"
                tone="danger"
                busyLabel="Deleting..."
                onConfirm={() => remove(c.id)}
              />
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
