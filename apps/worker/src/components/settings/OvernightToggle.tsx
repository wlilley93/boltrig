import { ExactApprovalFinalizer } from "../ExactApprovalFinalizer";
import { SettingsGroup, SettingsInfo, SettingsRow, SettingsToggle } from "./rowKit";
import { useOvernightBehaviour } from "./useOvernightBehaviour";

export function OvernightToggle() {
  const controller = useOvernightBehaviour();
  if (controller.state === "loading") {
    return <p className="muted small">Reading overnight behaviour…</p>;
  }
  if (controller.state === "unavailable" || !controller.organisation) {
    return <p className="notice">Overnight behaviour could not be read.</p>;
  }
  return (
    <>
      <SettingsGroup>
        <SettingsRow
          control={(
            <div className="settings-status">
              <SettingsInfo
                label="About overnight"
                text="Allows Boltrig to prepare a checked model adapter from approved work when an overnight worker is available. Nothing is applied automatically."
              />
              <SettingsToggle
                disabled={controller.busy || controller.finalizer.busy}
                label={`${controller.enabled ? "Disable" : "Enable"} overnight`}
                on={controller.enabled}
                onToggle={(next) => void controller.change(next)}
              />
            </div>
          )}
          title="Overnight"
        />
      </SettingsGroup>
      {controller.message && (
        <p className="console-foot" role="status">{controller.message}</p>
      )}
      <ExactApprovalFinalizer controller={controller.finalizer} />
    </>
  );
}
