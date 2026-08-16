import { useEffect, useRef } from "react";

import type { CharacterId } from "../../character";
import { saveSkinLocal } from "../../character";
import { skinFor, useCharacter, useSkin } from "../characters";
import { FamiliarStage } from "../familiar/FamiliarStage";
import { JarvisStage } from "../jarvis/JarvisStage";
import { CompanionCarousel } from "./CompanionCarousel";
import { COMPANIONS, companionIndex } from "./companionCatalogue";
import { playCompanionPreview } from "./companionVoicePreview";
import { SkinPicker } from "./SkinPicker";
import type { CompanionPreview } from "./useCompanionPreview";
import { useCompanionPreview } from "./useCompanionPreview";

export function CompanionStep({
  selected,
  onSelect,
}: {
  selected: CharacterId;
  onSelect: (id: CharacterId) => void;
}) {
  const preview = useCompanionPreview();
  const index = companionIndex(selected);
  const character = useCharacter(selected);
  const skin = skinFor(character, useSkin());

  // ARRIVING somewhere plays that voice, which is not the same as CLICKING.
  // Chevrons, dots and arrow keys all arrive, and each used to be silent while
  // only a click spoke. Keyed on the id rather than the index so a rail
  // reordering cannot make it replay the wrong companion.
  const spoken = useRef<CharacterId | null>(null);
  useEffect(() => {
    if (spoken.current === selected) return;
    spoken.current = selected;
    playCompanionPreview(selected);
  }, [selected]);

  return (
    <div className="onboarding-step companion-step">
      <div className="onboarding-heading onboarding-rise">
        <p className="onboarding-kicker">Make it yours</p>
        <h1>Choose your companion</h1>
        <p>Choose who you’d like to work with. You can switch at any time.</p>
      </div>
      <CompanionCarousel
        art={<CompanionArt id={selected} preview={preview} skin={skin} />}
        footer={
          <SkinPicker
            onSelect={(next) => saveSkinLocal(next)}
            selected={skin}
            skins={character.skins}
          />
        }
        index={index}
        items={COMPANIONS}
        onIndex={(next) => onSelect(COMPANIONS[next].id)}
      />
    </div>
  );
}

function CompanionArt({
  id,
  preview,
  skin,
}: {
  id: CharacterId;
  preview: CompanionPreview;
  skin: string;
}) {
  if (id === "familiar") {
    return <FamiliarStage mode="hero" state={preview.familiar} label="Familiar preview" />;
  }
  // `labels="shader"` keeps the DOM overlay off the preview: the onboarding card
  // is a portrait, and a HUD's legends over it read as chrome rather than as the
  // body. The neural skin has no labels either way.
  return <JarvisStage labels="shader" skin={skin} state={preview.jarvis} suspended={false} />;
}
