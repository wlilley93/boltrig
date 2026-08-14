import type { CharacterId } from "../../character";
import type { FamiliarGenotype } from "@wlilley93/boltrig-web-sdk";
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

const FAMILIAR_POSTER: FamiliarGenotype = {
  source: "agent_capability.name.v1",
  seed: 42,
  body: "cassini",
  palette: ["#dbeafe", "#3b82f6", "#172554"],
  markings: ["constellation"],
  accessories: ["orbit-ring"],
};

export function CompanionStep({
  name,
  onName,
  selected,
  onSelect,
}: {
  name: string;
  onName: (value: string) => void;
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
      <label className="onboarding-name onboarding-rise" style={{ "--onboarding-delay": "70ms" } as React.CSSProperties}>
        <span>What should Boltrig call you?</span>
        <input
          autoComplete="name"
          maxLength={80}
          onChange={(event) => onName(event.target.value)}
          placeholder="Your name"
          required
          value={name}
        />
      </label>
      <p className="companion-prompt onboarding-rise" style={{ "--onboarding-delay": "110ms" } as React.CSSProperties}>Now choose who meets you in the workspace.</p>
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

function CompanionArt({ id, active }: { id: CharacterId; active: boolean }) {
  if (id === "familiar") {
    return active
      ? <FamiliarStage mode="hero" state={RESTING_STAGE_STATE} label="Familiar preview" />
      : <FamiliarBadge genotype={FAMILIAR_POSTER} state="ready" label="Familiar preview" size={116} />;
  }
  return active
    ? <JarvisStage state={RESTING_JARVIS_STATE} suspended={false} />
    : <span className="jarvis-poster" aria-hidden="true"><i /><b>J</b></span>;
}
