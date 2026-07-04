import { ChipPickerCandidates } from "./ChipPickerCandidates";
import { ChipPickerInput } from "./ChipPickerInput";
import type { UseChipPickerResult } from "./useChipPicker";

export interface ChipPickerSearchProps extends UseChipPickerResult {
  placeholder?: string;
  ariaLabel?: string;
  disabled: boolean;
  allowFree: boolean;
}

export function ChipPickerSearch(props: ChipPickerSearchProps) {
  const {
    query,
    setQuery,
    setActive,
    setFreeError,
    listId,
    act,
    cands,
    showInput,
    showFreeRow,
    placeholder,
    ariaLabel,
    disabled,
    onKey,
    allowFree,
    addValue,
    addFree,
    freeError,
  } = props;
  return (
    <>
      <ChipPickerInput
        query={query}
        setQuery={setQuery}
        setActive={setActive}
        setFreeError={setFreeError}
        listId={listId}
        act={act}
        cands={cands}
        showInput={showInput}
        showFreeRow={showFreeRow}
        placeholder={placeholder}
        ariaLabel={ariaLabel}
        disabled={disabled}
        onKey={onKey}
      />
      {freeError && (
        <span className="ux-chips__err" role="alert">
          {freeError}
        </span>
      )}
      {showInput && (cands.length > 0 || showFreeRow) && (
        <ChipPickerCandidates
          cands={cands}
          act={act}
          listId={listId}
          query={query}
          allowFree={allowFree}
          addValue={addValue}
          addFree={addFree}
        />
      )}
    </>
  );
}
