// Round Five memory & knowledge surface (Epic MUI). Four sub-tabs behind
// internal state (no router): Recall, Browse, Remember and Ingest. Every view
// is scope-filtered to the caller server-side (SEC-40), so an empty result is
// scoping, not a bug, and each recalled fact carries provenance that shows WHY
// it is known. recall / remember / forget / ingest run the memory.* verbs
// through the kernel chokepoint; when memory is not enabled those routes return
// {status:"error", reason:"binding_not_found"} which this panel surfaces as
// "memory not enabled".

import { useState } from "react";

import {
  PageIntro,
} from "./ux";
import {
  MEMORY_TABS,
  type MemoryTab,
} from "./memoryPanel/helpers";
import { RecallTab } from "./memoryPanel/RecallTab";
import { BrowseTab } from "./memoryPanel/BrowseTab";
import { RememberTab } from "./memoryPanel/RememberTab";
import { IngestTab } from "./memoryPanel/IngestTab";

// --- the panel --------------------------------------------------------------

export function MemoryPanel() {
  const [sub, setSub] = useState<MemoryTab>("recall");

  return (
    <section className="panel">
      <PageIntro
        title="Memory"
        lead="This is what the assistant remembers - facts it can use to help you."
        how="Recall searches it, Browse lists it, Remember adds a fact, Ingest loads a whole source. You only ever see memory you're allowed to. If memory isn't enabled for your org, the actions report 'memory not enabled'."
      />

      <nav className="subtabs" aria-label="Memory sections">
        {MEMORY_TABS.map((t) => (
          <button
            key={t.id}
            className={`subtab ${sub === t.id ? "subtab--active" : ""}`}
            onClick={() => setSub(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {sub === "recall" && <RecallTab />}
      {sub === "browse" && <BrowseTab />}
      {sub === "remember" && <RememberTab />}
      {sub === "ingest" && <IngestTab />}
    </section>
  );
}
