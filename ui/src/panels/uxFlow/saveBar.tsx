/** SaveBar (N10, P17): the dirty-state bar pinned to the slide frame. */
// Pinned via position:sticky INSIDE the frame scroller, never fixed: the deck
// plane transform makes fixed resolve to the slide (reader-shell section 3).
// Render it as the last child of the slide's content.

import { useCallback, type ReactNode } from "react";
import { useArmConfirm, type UseArmConfirm } from "@/panels/uxFlow/armConfirm";

function SaveBarDiscard({
  discard,
}: {
  discard: UseArmConfirm;
}) {
  return (
    <span className="ux-savebar__confirm" {...discard.containerProps}>
      <span className="ux-savebar__restate">
        Discard changes? Your edits since the last save are lost.
      </span>
      {discard.error && (
        <span className="ux-arm__error" role="alert">
          {discard.error}
        </span>
      )}
      <button
        type="button"
        className="btn btn--sm ux-btn--danger"
        disabled={discard.busy}
        onClick={discard.confirm}
      >
        {discard.busy ? "Discarding..." : "Confirm discard"}
      </button>
      <button
        type="button"
        className="btn btn--sm btn--ghost"
        disabled={discard.busy}
        onClick={discard.disarm}
      >
        Cancel
      </button>
    </span>
  );
}

export function SaveBar({
  dirty,
  saving,
  label,
  saveLabel,
  onSave,
  onDiscard,
  governed,
}: {
  dirty: boolean;
  saving: boolean;
  label: ReactNode; // "Unsaved changes to invoice-flow"
  saveLabel: ReactNode; // ignored when governed (amendment 2 fixes the copy)
  onSave: () => void;
  onDiscard: () => void | Promise<void>;
  // true when the save traverses a control.* verb: the FIRST submit always
  // 202s (dispatch.py:213), so the button says so and the foreshadow renders
  governed?: boolean;
}) {
  const discard = useArmConfirm(
    useCallback(async () => {
      await onDiscard();
    }, [onDiscard]),
  );
  if (!dirty && !saving) return null;
  return (
    <div className="ux-savebar" role="status">
      <div className="ux-savebar__text">
        <span className="ux-savebar__label">{label}</span>
        {governed && (
          <span className="ux-savebar__foreshadow">
            This is a high-consequence change. It will pause for a human
            approval before it takes effect.
          </span>
        )}
      </div>
      <div className="ux-savebar__actions">
        {discard.armed ? (
          <SaveBarDiscard discard={discard} />
        ) : (
          <button
            type="button"
            className="btn btn--ghost"
            disabled={saving}
            onClick={discard.arm}
          >
            Discard
          </button>
        )}
        <button
          type="button"
          className="btn btn--primary"
          disabled={saving || !dirty}
          onClick={onSave}
        >
          {saving
            ? governed
              ? "Requesting..."
              : "Saving..."
            : governed
              ? "Request change"
              : saveLabel}
        </button>
      </div>
    </div>
  );
}
