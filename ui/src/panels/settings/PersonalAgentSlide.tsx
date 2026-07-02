// Settings / Personal Agent: the delegation-capped assistant that runs as you
// (SEC-30). Named PersonalAgentSlide to avoid colliding with panels/AgentSlide
// (the agents row's per-agent slide).
// Mechanical extraction of PersonalAgentSection from SettingsPanel.tsx (Beat 5).

import { useState } from "react";

import { api } from "../../api/client";
import { useFetch } from "../../useFetch";
import { GrantList, csvToList, errText } from "../shared";
import { PageIntro } from "../ux";

function PersonalAgentSection() {
  const agent = useFetch(() => api.meAgent(), []);

  const [runtime, setRuntime] = useState("pi-worker");
  const [skills, setSkills] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function configure() {
    setBusy(true);
    setMsg(null);
    setError(null);
    try {
      const res = await api.configurePersonalAgent({
        runtime: runtime.trim() || "pi-worker",
        skills: csvToList(skills),
      });
      setMsg(`Saved agent ${res.id} (owner ${res.owner}).`);
      agent.reload();
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  const current = agent.data?.agent ?? null;

  return (
    <div className="cols">
      <div className="list-card">
        <div className="list-card__head">
          <h3>Current agent</h3>
          <button className="btn" onClick={() => agent.reload()}>
            Refresh
          </button>
        </div>
        <div className="list-card__body">
          {agent.loading && !agent.data && <p className="muted">Loading...</p>}
          {agent.error && (
            <p className="error">Failed to load: {agent.error}</p>
          )}
          {!agent.loading && current === null && (
            <p className="muted">No personal agent configured yet.</p>
          )}
          {current && (
            <>
              <div className="row-line">
                <span className="muted">runtime</span>
                <code>{current.runtime}</code>
              </div>
              <div className="row-line">
                <span className="muted">enabled</span>
                <span className={`badge ${current.enabled ? "badge--ok" : ""}`}>
                  {current.enabled ? "on" : "off"}
                </span>
              </div>
              <div className="row-line">
                <span className="muted">skills</span>
                <GrantList grants={current.skills} />
              </div>
            </>
          )}
          <p className="muted">
            Your agent runs on-behalf-of you and its grants are delegated and
            capped to your own, so it can never act beyond you (SEC-30). Invoke
            it from the Me tab.
          </p>
        </div>
      </div>

      <div className="form">
        <div className="form__title">Configure</div>
        <div className="form__grid">
          <label className="field">
            <span>runtime</span>
            <input
              value={runtime}
              onChange={(e) => setRuntime(e.target.value)}
            />
          </label>
          <label className="field">
            <span>skills (comma list)</span>
            <input value={skills} onChange={(e) => setSkills(e.target.value)} />
          </label>
        </div>
        <div className="form__actions">
          <button
            className="btn btn--primary"
            disabled={busy}
            onClick={() => void configure()}
          >
            {busy ? "..." : "Save agent"}
          </button>
          {msg && <span className="ok">{msg}</span>}
          {error && <span className="error">{error}</span>}
        </div>
      </div>
    </div>
  );
}

export function PersonalAgentSlide() {
  return (
    <section className="panel">
      <PageIntro title="Personal Agent" lead="The assistant that runs as you." />
      <PersonalAgentSection />
    </section>
  );
}
