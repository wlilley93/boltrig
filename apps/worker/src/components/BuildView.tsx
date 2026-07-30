import { useEffect, useState } from "react";
import type { CapabilityChange } from "@wlilley93/boltrig-web-sdk";

import { client } from "../client";
import { Topbar } from "./Shell";
import { AdaptersBuild } from "./build/AdaptersBuild";
import { RegistryBuild } from "./build/RegistryBuild";
import { SkillsBuild } from "./build/SkillsBuild";
import { ModelEndpointsBuild } from "./build/ModelEndpointsBuild";
import { SpawnRulesBuild } from "./build/SpawnRulesBuild";
import { CapabilityRunner } from "./build/CapabilityRunner";

type BuildTab = "run" | "registry" | "skills" | "adapters" | "models" | "routing" | "history";

export function BuildView() {
  const [tab, setTab] = useState<BuildTab>("run");
  return (
    <div className="page">
      <Topbar title="Build" status="Governed authoring" />
      <div className="page-content">
        <div className="page-intro">
          <div>
            <h2>Extend what Boltrig can do</h2>
            <p>Author nouns, verbs, skills and adapters as data. Activation and high-consequence changes still pass through the kernel.</p>
          </div>
        </div>
        <nav className="tabs" aria-label="Build sections">
          {(["run", "registry", "skills", "adapters", "models", "routing", "history"] as const).map((item) => (
            <button
              className={tab === item ? "active" : ""}
              aria-current={tab === item ? "page" : undefined}
              onClick={() => setTab(item)}
              key={item}
            >
              {item[0].toUpperCase() + item.slice(1)}
            </button>
          ))}
        </nav>
        {tab === "run" && <CapabilityRunner />}
        {tab === "registry" && <RegistryBuild />}
        {tab === "skills" && <SkillsBuild />}
        {tab === "adapters" && <AdaptersBuild />}
        {tab === "models" && <ModelEndpointsBuild />}
        {tab === "routing" && <SpawnRulesBuild />}
        {tab === "history" && <CapabilityHistory />}
      </div>
    </div>
  );
}

function CapabilityHistory() {
  const [changes, setChanges] = useState<CapabilityChange[]>([]);
  const [message, setMessage] = useState("");

  function refresh() {
    setMessage("");
    void client.capabilityChangelog()
      .then((result) => setChanges(result.changes))
      .catch(() => setMessage("Capability history is unavailable for this identity."));
  }

  useEffect(refresh, []);
  return (
    <section className="settings-card">
      <div className="section-heading">
        <div><p className="eyebrow">Governed history</p><h2>Capability changes</h2></div>
        <button className="secondary-button" onClick={refresh}>Refresh</button>
      </div>
      <p className="muted small">Recent authoring actions from the tamper-evident audit stream. Raw configuration diffs and rollback remain in Operator.</p>
      {message && <p className="notice" role="status">{message}</p>}
      <div className="data-list" aria-label="Capability changes">
        {changes.map((change) => (
          <div className="data-row static" key={`${change.ts}-${change.actor}-${change.action}-${change.ref}`}>
            <span className={`activity-dot ${change.status === "ok" ? "ok" : "paused"}`} />
            <span className="data-row-copy"><strong>{change.action}</strong><small>{change.actor} · {new Date(change.ts).toLocaleString()}</small></span>
            <span className="row-meta">{change.ref || change.status}</span>
          </div>
        ))}
        {changes.length === 0 && !message && <p className="muted">No capability changes are visible.</p>}
      </div>
    </section>
  );
}
