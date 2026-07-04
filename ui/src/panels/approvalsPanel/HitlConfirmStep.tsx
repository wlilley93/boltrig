import { InfoCallout } from "@/panels/ux";
import { optionClass } from "./hitlUtils";

// The deliberate second step: restate the choice, require a confirm.
export function HitlConfirmStep({
  arming,
  busy,
  onConfirm,
  onCancel,
}: {
  arming: string;
  busy: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <InfoCallout tone={arming.toLowerCase() === "reject" ? "warn" : "consequence"}>
      <div className="kv">
        <span>
          Confirm: <strong>{arming}</strong> this action? It runs as soon as you
          confirm.
        </span>
      </div>
      <div className="kv" style={{ marginTop: 6 }}>
        <button className={optionClass(arming)} disabled={busy} onClick={onConfirm}>
          {busy ? "Recording..." : `Confirm ${arming}`}
        </button>
        <button className="btn btn--ghost" disabled={busy} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </InfoCallout>
  );
}
