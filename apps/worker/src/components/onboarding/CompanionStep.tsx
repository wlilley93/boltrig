import type { CharacterId } from "../../character";
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
        <p>Choose who you’d like to work with. You can switch at any time.</p>
      </div>
      <p className="companion-prompt onboarding-rise" style={{ "--onboarding-delay": "70ms" } as React.CSSProperties}>Meet them both.</p>
      <div className="companion-grid" role="radiogroup" aria-label="Companion">
        {CHOICES.map((choice, index) => {
          const active = selected === choice.id;
          return (
            <button
              aria-checked={active}
              className={`companion-card onboarding-rise${active ? " selected" : ""}`}
              key={choice.id}
              data-companion={choice.id}
              onKeyDown={(event) => handleCompanionKey(event, onSelect)}
              onClick={() => onSelect(choice.id)}
              role="radio"
              style={{ "--onboarding-delay": `${150 + index * 90}ms` } as React.CSSProperties}
              tabIndex={active ? 0 : -1}
              type="button"
            >
              <span className={`companion-art ${choice.id}`} aria-hidden="true">
                <CompanionArt id={choice.id} />
              </span>
              <span className="companion-copy">
                <strong>{choice.name}</strong>
                <span>{choice.blurb}</span>
                <small>{choice.note}</small>
              </span>
              {active ? <span className="companion-check" aria-hidden="true">✓</span> : null}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function handleCompanionKey(
  event: React.KeyboardEvent<HTMLButtonElement>,
  onSelect: (id: CharacterId) => void,
) {
  if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) return;
  event.preventDefault();
  const cards = Array.from(
    event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>("[data-companion]") ?? [],
  );
  const current = cards.indexOf(event.currentTarget);
  const backwards = event.key === "ArrowLeft" || event.key === "ArrowUp";
  const next = cards[(current + (backwards ? -1 : 1) + cards.length) % cards.length];
  const id = next?.dataset.companion;
  if (id === "familiar" || id === "jarvis") onSelect(id);
  next?.focus();
}

function CompanionArt({ id }: { id: CharacterId }) {
  if (id === "familiar") {
    return <FamiliarStage mode="hero" state={RESTING_STAGE_STATE} label="Familiar preview" />;
  }
  return <JarvisStage labels="shader" state={RESTING_JARVIS_STATE} suspended={false} />;
}
