import { useRef } from "react";
import type { FamiliarGenotype, FamiliarPhenotypeResponse } from "@wlilley93/boltrig-web-sdk";
import { FamiliarBadge, familiarPalette } from "./FamiliarBadge";
import { familiarVisualIdentity } from "./FamiliarGenotype";
import { useFamiliarRenderer } from "./useFamiliarRenderer";
import {
  familiarBusy,
  familiarModeLabel,
  type FamiliarPresentationMode,
  type FamiliarStageState,
} from "./FamiliarState";
import "./familiar.css";

// The one premium visual body (ADR 0025). Mount at most one Stage per Worker
// client — badges stay cheap CSS. The Stage owns its renderer's lifecycle and
// falls back to the badge the moment the renderer cannot run, so there is
// never a blank stage.
export function FamiliarStage({
  mode,
  state,
  phenotype,
  genotype,
  label,
}: {
  mode: FamiliarPresentationMode;
  state: FamiliarStageState;
  phenotype?: FamiliarPhenotypeResponse | null;
  genotype?: FamiliarGenotype | null;
  label?: string;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const rendererKind = useFamiliarRenderer({
    genotype, host: hostRef, mode, phenotype, state,
  });

  const busy = familiarBusy(state);
  const identity = familiarVisualIdentity(genotype);
  const accessibleName = familiarStageAccessibleName(label);
  const spoken = familiarModeLabel(state.mode);
  return (
    <>
      <div
        ref={hostRef}
        className={`familiar-stage ${mode}${rendererKind === "badge" ? " fallback" : ""}`}
        role="img"
        aria-label={accessibleName}
        aria-busy={rendererKind === "pending" ? "true" : undefined}
        data-familiar-body={identity.body}
        data-genotype-source={identity.source}
        data-renderer={rendererKind}
        style={familiarPalette(identity.palette)}
      >
        {rendererKind === "badge" && (
          <FamiliarBadge
            decorative
            state={busy ? "working" : "ready"}
            genotype={genotype}
            label={label}
          />
        )}
      </div>
      {/* THE STATE, SAID OUT LOUD, and OUTSIDE the body rather than inside it.
          A Stage is often the only indicator of what the machine is doing, so
          without this a screen-reader user has no indicator at all -- and the
          `aria-label` above cannot be it, because that is a NAME: role="img" is
          read once when focus reaches it, not each time the state changes.
          It has to be a SIBLING because role="img" replaces its own subtree in
          the accessibility tree; a live region nested inside one is never
          announced, which is the version of this fix that looks right in the
          markup and does nothing at all. */}
      <span aria-live="polite" className="familiar-stage-status">
        {`${accessibleName} ${spoken}`}
      </span>
    </>
  );
}

function familiarStageAccessibleName(label?: string) {
  const trimmed = label?.trim();
  return trimmed?.toLocaleLowerCase() === "familiar"
    ? trimmed
    : `${trimmed || "Boltrig"} Familiar`;
}
