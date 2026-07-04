import type { TriggerKind } from "./types";

interface TriggerPaletteProps {
  onAdd: (triggerType: TriggerKind) => void;
}

export function TriggerPalette({ onAdd }: TriggerPaletteProps) {
  return (
    <div className="form">
      <div className="form__title">Triggers (entry markers)</div>
      <p className="muted">
        Visual entry points only. They are not steps and are excluded from the
        saved definition.
      </p>
      <div className="kv">
        <button className="btn" onClick={() => onAdd("chat")}>
          + chat
        </button>
        <button className="btn" onClick={() => onAdd("cron")}>
          + cron
        </button>
        <button className="btn" onClick={() => onAdd("webhook")}>
          + webhook
        </button>
      </div>
    </div>
  );
}
