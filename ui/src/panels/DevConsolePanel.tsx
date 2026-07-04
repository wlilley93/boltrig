// Developer console (Capability plane). Surfaces three client-ready kernel
// endpoints that no other panel exposes: direct verb invoke (POST /v1/invoke),
// ephemeral agent spawn (POST /v1/spawn) and the generated adapter source
// (GET /v1/adapters/{id}/source). Every call is server-authoritative: a denial,
// a pending-human pause or a degraded result is rendered faithfully, exactly as
// the kernel returned it (the AdminPanel pattern). The role gate on the tab is
// cosmetic; the chokepoint is the real gate (a 403 returns a denial body).

import { useState } from "react";

import { api } from "../api/client";

import { useFetch } from "../useFetch";
import { CodeBlock, errText } from "./shared";
import { Field, PageIntro, Select } from "./ux";
import { InvokeSection } from "./devConsole/InvokeSection";
import { SpawnSection } from "./devConsole/SpawnSection";

export function DevConsolePanel() {
  // The scoped verb registry powers the invoke picker; the adapter inventory
  // powers the source viewer; the skills list powers the spawn chips. All are
  // caller-scoped server-side.
  const caps = useFetch(() => api.capabilities(), []);
  const adapters = useFetch(() => api.adapters(), []);
  const skillsList = useFetch(() => api.skills(), []);

  // --- Adapter source ---
  const [adapterId, setAdapterId] = useState("");
  const [srcBusy, setSrcBusy] = useState(false);
  const [srcError, setSrcError] = useState<string | null>(null);
  const [source, setSource] = useState<string | null>(null);

  const adapterRecords = adapters.data?.adapters ?? [];

  async function loadSource() {
    if (!adapterId.trim()) {
      setSrcError("Pick an adapter first.");
      return;
    }
    setSrcBusy(true);
    setSrcError(null);
    setSource(null);
    try {
      const res = await api.adapterSource(adapterId.trim());
      if (res.error) setSrcError(res.error);
      else setSource(res.source ?? "");
    } catch (err) {
      setSrcError(errText(err));
    } finally {
      setSrcBusy(false);
    }
  }

  return (
    <section className="panel">
      <PageIntro
        title="Dev console"
        lead="Run one verb at a time, by hand, to test or debug a capability."
        how="Pick a verb from the registry; the kernel checks your grants and shows the real result - success, a denial, or a pause for human approval. Nothing here bypasses governance."
        actions={
          <button
            className="btn"
            onClick={() => {
              caps.reload();
              adapters.reload();
              skillsList.reload();
            }}
          >
            Refresh
          </button>
        }
      />

      <InvokeSection caps={caps} />
      <SpawnSection skillsList={skillsList} />

      <div className="form">
        <div className="form__title">Adapter source</div>
        <p className="ux-hint">
          The generated source for a registered adapter, read-only - useful to
          see exactly what a verb runs.
        </p>
        <div className="form__actions">
          <Field label="Adapter">
            <Select
              value={adapterId}
              ariaLabel="Pick an adapter"
              onChange={setAdapterId}
              options={[
                { value: "", label: adapters.loading ? "Loading adapters..." : "Choose an adapter..." },
                ...adapterRecords.map((a) => ({
                  value: a.id,
                  label: `${a.id} (${a.runtime} ${a.version})`,
                })),
              ]}
            />
          </Field>
          <button className="btn" disabled={srcBusy} onClick={loadSource}>
            {srcBusy ? "Loading..." : "View source"}
          </button>
          {srcError && <span className="error">{srcError}</span>}
        </div>
        {adapters.error && (
          <p className="error">Could not load adapters: {adapters.error}</p>
        )}
        {source !== null && <CodeBlock value={source} />}
      </div>
    </section>
  );
}
