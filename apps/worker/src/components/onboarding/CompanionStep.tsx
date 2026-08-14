import type { CharacterId } from "../../character";
import { FamiliarBadge } from "../familiar/FamiliarBadge";
import { FamiliarStage } from "../familiar/FamiliarStage";
import { RESTING_STAGE_STATE } from "../familiar/FamiliarState";
import { JarvisStage } from "../jarvis/JarvisStage";
import { RESTING_JARVIS_STATE } from "../jarvis/JarvisState";

interface CompanionChoice {
  id: CharacterId;
  name: string;
  blurb: string;
  note: string;
}

const CHOICES: CompanionChoice[] = [
  {
    id: "familiar",
    name: "Familiar",
    blurb: "A living presence with a private inner life.",
    note: "Warm, organic and quietly expressive.",
  },
  {
    id: "jarvis",
    name: "Jarvis",
    blurb: "An instrument for the machine's measured state.",
    note: "Precise, technical and visibly connected to the work.",
  },
];

export function CompanionStep({
  selected,
  onSelect,
}: {
  selected: CharacterId;
  onSelect: (id: CharacterId) => void;
}) {
  return (
    <div className="onboarding-step companion-step">
      <div className="onboarding-heading onboarding-rise">
        <p className="onboarding-kicker">Make it yours</p>
        <h1>Choose your companion</h1>
        <p>You can switch later. The companion changes how Boltrig feels, never what it is allowed to do.</p>
      </div>
      <div className="companion-grid" role="radiogroup" aria-label="Companion">
        {CHOICES.map((choice, index) => {
          const active = selected === choice.id;
          return (
            <button
              aria-checked={active}
              className={`companion-card onboarding-rise${active ? " selected" : ""}`}
              key={choice.id}
              onClick={() => onSelect(choice.id)}
              role="radio"
              style={{ "--onboarding-delay": `${90 + index * 90}ms` } as React.CSSProperties}
              type="button"
            >
              <span className={`companion-art ${choice.id}`}>
                <CompanionArt id={choice.id} active={active} />
              </span>
              <span className="companion-copy">
                <strong>{choice.name}</strong>
                <span>{choice.blurb}</span>
                <small>{choice.note}</small>
              </span>
              <span className="companion-check" aria-hidden="true">✓</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function CompanionArt({ id, active }: { id: CharacterId; active: boolean }) {
  if (id === "familiar") {
    return active
      ? <FamiliarStage mode="hero" state={RESTING_STAGE_STATE} label="Familiar preview" />
      : <FamiliarBadge state="ready" label="Familiar preview" size={116} />;
  }
  return active
    ? <JarvisStage state={RESTING_JARVIS_STATE} suspended={false} />
    : <span className="jarvis-poster" aria-hidden="true"><i /><b>J</b></span>;
}
