import type { ChipOption } from "./ChipPickerChips";

export interface ChipPickerCandidatesProps {
  cands: ChipOption[];
  act: number;
  listId: string;
  query: string;
  allowFree: boolean;
  addValue: (v: string) => void;
  addFree: () => void;
}

export function ChipPickerCandidates({
  cands,
  act,
  listId,
  query,
  allowFree,
  addValue,
  addFree,
}: ChipPickerCandidatesProps) {
  const showFreeRow = allowFree && query.trim().length > 0 && !cands.some((c) => c.value === query.trim());
  return (
    <div className="ux-chips__list" role="listbox" id={listId}>
      {cands.map((c, i) =>
        c.disabled ? (
          <div
            key={c.value}
            id={`${listId}-o${i}`}
            role="option"
            aria-disabled="true"
            aria-selected="false"
            className="ux-chips__cand ux-chips__cand--off"
          >
            <span>{c.label ?? c.value}</span>
            {c.disabledReason && <span className="ux-chips__cand-why">{c.disabledReason}</span>}
          </div>
        ) : (
          <button
            key={c.value}
            type="button"
            id={`${listId}-o${i}`}
            role="option"
            aria-selected={i === act}
            tabIndex={-1}
            className={`ux-chips__cand ${i === act ? "ux-chips__cand--act" : ""}`}
            onClick={() => addValue(c.value)}
          >
            <span>{c.label ?? c.value}</span>
            {c.hint && <span className="ux-chips__cand-hint">{c.hint}</span>}
          </button>
        ),
      )}
      {showFreeRow && (
        <button
          type="button"
          role="option"
          aria-selected="false"
          tabIndex={-1}
          className="ux-chips__cand"
          onClick={addFree}
        >
          <span>Add "{query.trim()}"</span>
        </button>
      )}
    </div>
  );
}
