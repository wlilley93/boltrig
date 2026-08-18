import type { CharacterId } from "../../character";
import { saveSkinLocal } from "../../character";
import { skinFor, useCharacter, useCharacterOptions, useSkin } from "../characters";
import { SettingsRow, SettingsSegmented } from "./rowKit";

/**
 * Which body is on the Stage, and what it wears.
 *
 * TOGETHER AND SEPARATE. They are one question asked twice -- who, then which
 * look -- and they are the only rows in settings that read the character
 * registry. Keeping them beside the theme and density rows meant AppearanceGroup
 * carried two registry hooks it had no other use for, and grew past the
 * structural floor the moment a second companion question existed.
 *
 * NEITHER ROW NAMES A CHARACTER. The companion row offers whatever is
 * registered; the appearance row offers whatever the SELECTED character
 * declares, and renders nothing when it declares fewer than two. A
 * `character === "jarvis"` test in either would be the special case the
 * registry exists to prevent.
 */
export function CompanionRows({
  busy,
  character,
  onChangeCharacter,
}: {
  busy: boolean;
  character: CharacterId;
  onChangeCharacter(next: CharacterId): void;
}) {
  const { options, values } = useCharacterOptions();
  return (
    <>
      <SettingsRow
        control={(
          <SettingsSegmented
            disabled={busy}
            label="Companion"
            onChange={(label) => onChangeCharacter(values[label] ?? "familiar")}
            options={options}
            value={labelFor(character, values)}
          />
        )}
        desc="Choose the body shown on the Stage. The Familiar has a private animated presence; Jarvis visualises measured runtime state."
        tech="agent.character"
        title="Companion"
      />
      <SkinRow busy={busy} character={character} />
    </>
  );
}

/**
 * The appearance row, which is absent rather than empty for a character with
 * one look -- a picker offering a single option is a control that cannot be
 * used, and reads as something being broken.
 */
function SkinRow({ busy, character }: { busy: boolean; character: CharacterId }) {
  const selected = useCharacter(character);
  const active = skinFor(selected, useSkin());
  const skins = selected.skins ?? [];
  if (skins.length < 2) return null;
  const nameOf = (skin: { id: string; name?: string }) => skin.name ?? skin.id;
  return (
    <SettingsRow
      control={(
        <SettingsSegmented
          disabled={busy}
          label="Appearance"
          onChange={(label) => {
            const picked = skins.find((skin) => nameOf(skin) === label);
            if (picked) saveSkinLocal(picked.id);
          }}
          options={skins.map(nameOf)}
          value={nameOf(skins.find((skin) => skin.id === active) ?? skins[0])}
        />
      )}
      desc="Which body this companion wears. Presentation only — it changes nothing about how the agent answers."
      tech="agent.character.skin"
      title="Appearance"
    />
  );
}

/** The display name for a stored id, falling back rather than showing a raw id. */
function labelFor(id: CharacterId, values: Record<string, CharacterId>): string {
  const found = Object.entries(values).find(([, value]) => value === id);
  return found ? found[0] : "Familiar";
}
