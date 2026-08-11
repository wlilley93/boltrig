import { useEffect, useState } from "react";
import type {
  SpawnRulePolicyResponse,
  SpawnRuleSimulationResponse,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";
import { Unavailable } from "../Shell";

function tagsFromText(value: string): string[] {
  return value
    .split(",")
    .map((tag) => tag.trim().toLowerCase())
    .filter((tag, index, all) => Boolean(tag) && all.indexOf(tag) === index);
}

export function SpawnRulesBuild() {
  const [policy, setPolicy] =
    useState<SpawnRulePolicyResponse["policy"] | null>(null);
  const [tags, setTags] = useState("");
  const [simulation, setSimulation] =
    useState<SpawnRuleSimulationResponse | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  function refresh() {
    setSimulation(null);
    setMessage("");
    void client.spawnRules()
      .then((result) => setPolicy(result.policy))
      .catch(() => {
        setPolicy(null);
        setMessage("Effective spawn-rule policy is unavailable.");
      });
  }

  useEffect(refresh, []);

  async function simulate(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      const result = await client.simulateSpawnRules(tagsFromText(tags));
      setSimulation(result);
    } catch {
      setSimulation(null);
      setMessage("The no-side-effect rule preview is unavailable.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="build-layout">
      <section className="settings-card build-inventory">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Effective routing policy</p>
            <h2>Spawn rules</h2>
          </div>
          <button className="secondary-button" onClick={refresh}>Refresh</button>
        </div>
        <p className="muted small">
          Rules can narrow delegated capability, skills and depth. They never
          widen grants. Live execution accepts only server-trusted
          classification; text entered here is preview-only.
        </p>
        {policy ? (
          <>
            <p className="notice" role="status">
              {policy.state} · {policy.source?.replaceAll("_", " ") ?? "source unavailable"}
              {policy.revision_id !== null ? ` · revision ${policy.revision_id}` : ""}
            </p>
            <div className="data-list" aria-label="Spawn rules">
              {policy.rules.map((rule) => (
                <div className="data-row static" key={rule.id}>
                  <span className="activity-dot ok" />
                  <span className="data-row-copy">
                    <strong>{rule.id}</strong>
                    <small>
                      all of: {rule.intent_tags.join(", ")} · capability {rule.capability}
                    </small>
                  </span>
                  <span className="row-meta">
                    priority {rule.priority}
                    {rule.max_depth === null ? "" : ` · depth ≤ ${rule.max_depth}`}
                  </span>
                </div>
              ))}
              {policy.rules.length === 0 && (
                <p className="muted">No spawn rules are configured.</p>
              )}
            </div>
            {policy.conflicts.length > 0 && (
              <Unavailable title="Rule conflicts fail closed">
                {policy.conflicts.map((conflict) => (
                  <span key={`${conflict.priority}-${conflict.rules.join("-")}`}>
                    Priority {conflict.priority}: {conflict.rules.join(", ")}
                    {" "}for {conflict.example_intent_tags.join(", ")}.{" "}
                  </span>
                ))}
              </Unavailable>
            )}
          </>
        ) : (
          <Unavailable title="Spawn policy unavailable">
            {message || "Loading effective policy…"}
          </Unavailable>
        )}
      </section>

      <form className="settings-card author-form" onSubmit={(event) => void simulate(event)}>
        <p className="eyebrow">No-side-effect analysis</p>
        <h2>Preview trusted tags</h2>
        <p>
          This answers which rule would match. It does not classify a task,
          authorize a spawn, reserve budget or execute an agent.
        </p>
        <label>
          <span>Intent tags, comma separated</span>
          <input
            className="field-control"
            value={tags}
            onChange={(event) => {
              setTags(event.target.value);
              setSimulation(null);
            }}
            placeholder="research, customer-sensitive"
          />
        </label>
        <button className="primary-button" disabled={busy}>
          {busy ? "Previewing…" : "Preview rule"}
        </button>
        {simulation && (
          <div className="notice" role="status">
            <strong>{simulation.status.replaceAll("_", " ")}</strong>
            {simulation.selection && (
              <span>
                {" "}{simulation.selection.id} selects capability{" "}
                {simulation.selection.capability}.
              </span>
            )}
            {simulation.reason && <span> {simulation.reason}</span>}
            <small className="block">
              Preview-only input; no runtime trusted these tags.
            </small>
          </div>
        )}
        {message && <p className="notice" role="status">{message}</p>}
        <p className="muted small">
          Versioned authoring remains unavailable until Boltrig has a canonical
          trusted classification source.
        </p>
      </form>
    </div>
  );
}
