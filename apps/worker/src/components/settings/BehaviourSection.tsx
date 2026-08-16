import { useEffect, useState } from "react";

import { KnowledgeToggle } from "./KnowledgeToggle";
import { OvernightToggle } from "./OvernightToggle";
import { SectionHead } from "./SectionHead";
import { SensingSection } from "./SensingSection";
import "./behaviour.css";

export type BehaviourView = "presence" | "overnight" | "sight" | "memory";

const VIEWS: Array<{ id: BehaviourView; label: string }> = [
  { id: "presence", label: "Presence" },
  { id: "overnight", label: "Overnight" },
  { id: "sight", label: "Sight" },
  { id: "memory", label: "Memory" },
];

export function BehaviourSection({
  head = true,
  initialView = "presence",
}: {
  head?: boolean;
  initialView?: BehaviourView;
}) {
  const [view, setView] = useState<BehaviourView>(initialView);
  useEffect(() => setView(initialView), [initialView]);
  return (
    <>
      {head && <SectionHead section="behaviour" />}
      <div aria-label="Behaviour settings" className="behaviour-tabs" role="tablist">
        {VIEWS.map((item) => (
          <button
            aria-controls={`behaviour-panel-${item.id}`}
            aria-selected={view === item.id}
            key={item.id}
            onClick={() => setView(item.id)}
            role="tab"
            type="button"
          >
            {item.label}
          </button>
        ))}
      </div>
      <div id={`behaviour-panel-${view}`} role="tabpanel">
        {view === "presence" && <SensingSection head={false} view="presence" />}
        {view === "overnight" && <OvernightToggle />}
        {view === "sight" && <SensingSection head={false} view="sight" />}
        {view === "memory" && <KnowledgeToggle />}
      </div>
    </>
  );
}
