/**
 * A page whose only job is to let a human LOOK at the familiars.
 *
 * This exists because of a defect it would have caught in seconds. The first cut of the
 * genotype compiled, linked, passed its tests, and demonstrably delivered its uniform to the
 * shader - and still drew a star-shaped wire around a perfectly circular ball, because the
 * body's interior never consulted the genotype at all. No test asserted "it looks right",
 * and no test reasonably could. The only thing that finds that class of bug is a picture.
 *
 * Dev-only: it is a separate Vite entry, so it never enters the app bundle.
 * Run `pnpm dev` and open /familiar-preview.html.
 */

import { StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";

import { Familiar } from "@/familiar/Familiar";
import { AgentAvatar } from "@/panels/chat/AgentAvatar";
import type { ChatAgent } from "@/panels/chat/constants";
import { FamiliarDesigner } from "@/familiar/FamiliarDesigner";
import { deriveGenotype, type Genotype } from "@/familiar/genotype";
import type { RunFacts } from "@/familiar/phenotype";

import "@/styles.css";

const ROLES = ["orchestrator", "researcher", "reviewer", "builder", "guardian", "analyst"];
const STATES: RunFacts["status"][] = [
  "idle", "queued", "running", "awaiting_approval", "failed", "done", "offline",
];

function Grid(): JSX.Element {
  return (
    <section style={{ padding: 24 }}>
      <h2 style={{ fontSize: 14 }}>Six roles, five agents each</h2>
      <p style={{ fontSize: 12, opacity: 0.7, maxWidth: 640 }}>
        Every agent in a row shares its role's family; no two share a body. If a row ever looks
        uniform, the derivation has collapsed and the familiar has become decoration.
      </p>
      {ROLES.map((role) => (
        <div key={role} style={{ display: "flex", alignItems: "center", gap: 16, margin: "12px 0" }}>
          <span style={{ width: 110, fontSize: 12, opacity: 0.8 }}>{role}</span>
          {Array.from({ length: 5 }, (_, i) => (
            <Familiar key={i} agent={{ id: `${role}-${i}`, role }} size={64} run={{ status: "running" }} />
          ))}
        </div>
      ))}

      <h2 style={{ fontSize: 14, marginTop: 32 }}>One agent, every run state</h2>
      <p style={{ fontSize: 12, opacity: 0.7, maxWidth: 640 }}>
        Same body throughout. Only the mood changes, and it is derived from the run, so nothing
        here can be true of the picture and false of the record.
      </p>
      <div style={{ display: "flex", gap: 20, flexWrap: "wrap", marginTop: 12 }}>
        {STATES.map((status) => (
          <div key={status} style={{ textAlign: "center" }}>
            <Familiar agent={{ id: "reviewer-2", role: "reviewer" }} size={72} run={{ status, elapsedS: 90 }} />
            <div style={{ fontSize: 10, opacity: 0.7, marginTop: 4 }}>{status}</div>
          </div>
        ))}
      </div>

      <h2 style={{ fontSize: 14, marginTop: 32 }}>AgentAvatar, the real component</h2>
      <p style={{ fontSize: 12, opacity: 0.7, maxWidth: 640 }}>
        Everything above renders &lt;Familiar&gt; directly. This row is the component the chat
        actually uses - status dot, agent colour, the CSS that had to stop painting a flat disc
        behind a transparent body. A familiar that reads well on a bare page and badly here is
        a familiar that does not ship.
      </p>
      <div style={{ display: "flex", gap: 18, alignItems: "center", marginTop: 12, flexWrap: "wrap" }}>
        {(["active", "idle", "offline"] as const).flatMap((status) =>
          ROLES.slice(0, 4).map((role, i) => {
            const agent = {
              id: `${role}-${i}`, name: role, role, initials: role.slice(0, 2).toUpperCase(),
              // A TOKEN, not a hex literal. semanticTokens.test.ts caught the raw value here and
              // was right to: a raw colour in a preview is still a raw colour, and the point of
              // this page is to show what the product renders. A fixture painting itself
              // off-system shows a body the product cannot produce.
              //
              // The offending value is deliberately NOT quoted in this comment. The first fix
              // named it, and the gate went red again on the prose explaining the fix - the
              // scanner reads comments. That is the same trap opbox hit, where a token was
              // reported as consumed by the sentence explaining that nothing consumed it.
              color: "var(--chat-accent)", dept: "", status, snippet: "", time: "", tier: 1, history: [],
            } as ChatAgent;
            return (
              <div key={`${status}-${role}`} style={{ textAlign: "center" }}>
                <AgentAvatar agent={agent} size={36} />
                <div style={{ fontSize: 9, opacity: 0.6, marginTop: 4 }}>{status}</div>
              </div>
            );
          }),
        )}
      </div>

      <h2 style={{ fontSize: 14, marginTop: 32 }}>At the sizes it is actually seen</h2>
      <div style={{ display: "flex", gap: 14, alignItems: "center", marginTop: 12 }}>
        {[20, 24, 28, 32, 40, 56, 80].map((s) => (
          <Familiar key={s} agent={{ id: "builder-1", role: "builder" }} size={s} run={{ status: "running" }} />
        ))}
      </div>
    </section>
  );
}

function App(): JSX.Element {
  const [familiar, setFamiliar] = useState<Partial<Genotype> | null>(null);
  const [role, setRole] = useState("reviewer");
  return (
    // `.chat-v3` is not decoration here. The chat's colour tokens (--chat-ok, --chat-warn,
    // --chat-faint) are declared INSIDE that selector, so a harness that renders AgentAvatar
    // outside it shows every status dot in the fallback colour - a dark disc on a dark body.
    // That looked exactly like a real accessibility defect and was not one. A preview that
    // renders components outside their token scope is worse than no preview: it reports
    // failures that do not exist, and it would equally hide one that does.
    <div className="chat-v3" style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 360px", gap: 24 }}>
      <Grid />
      <aside style={{ padding: 24 }}>
        <label style={{ fontSize: 12, display: "grid", gap: 4, marginBottom: 12 }}>
          Role
          <select value={role} onChange={(e) => { setRole(e.target.value); setFamiliar(null); }}>
            {ROLES.map((r) => <option key={r}>{r}</option>)}
          </select>
        </label>
        <FamiliarDesigner agentId="demo-agent" role={role} value={familiar} onChange={setFamiliar} />
        <pre style={{ fontSize: 10, opacity: 0.6, marginTop: 12, whiteSpace: "pre-wrap" }}>
          {JSON.stringify(familiar ?? deriveGenotype({ id: "demo-agent", role }), null, 1)}
        </pre>
      </aside>
    </div>
  );
}

// Exposed for the asset renderer that produces the Figma artwork. It must call the SAME
// derivation the app uses, or the design system would document bodies the product does not
// draw - which is the exact failure mode a design system exists to prevent.
(window as unknown as { __deriveGenotype?: typeof deriveGenotype }).__deriveGenotype = deriveGenotype;

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
