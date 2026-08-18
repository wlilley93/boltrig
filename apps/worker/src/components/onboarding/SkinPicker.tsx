import type { CharacterSkin } from "@wlilley93/boltrig-web-sdk";

/**
 * Which body a character wears, when it offers more than one.
 *
 * INSIDE THE CARD, not on the rail. The rail answers "who am I working with";
 * this answers "what do they look like", and they are different questions.
 * Putting the Ultron skin on the rail as a third stop would have said Jarvis is
 * two characters -- which is exactly what the skin model exists to deny, and
 * what would have to be un-said later when a real Ultron is built.
 *
 * The component names no character. It renders whatever skins the active one
 * declares, and renders nothing at all when there are fewer than two -- so
 * Familiar shows no picker without anyone having written that down.
 */
export function SkinPicker({
  skins,
  selected,
  onSelect,
}: {
  skins: readonly CharacterSkin[] | undefined;
  selected: string;
  onSelect: (id: string) => void;
}) {
  if (!skins || skins.length < 2) return null;
  const active = skins.some((skin) => skin.id === selected) ? selected : skins[0].id;
  return (
    <div aria-label="Appearance" className="skin-picker" role="radiogroup">
      {skins.map((skin) => (
        <button
          aria-checked={skin.id === active}
          className={`skin-pill${skin.id === active ? " active" : ""}`}
          key={skin.id}
          onClick={() => onSelect(skin.id)}
          role="radio"
          title={skin.blurb}
          type="button"
        >
          {skin.name ?? skin.id}
        </button>
      ))}
    </div>
  );
}
