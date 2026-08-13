import { AuthCard, AuthSplash } from "./AuthShell";
import { useDesktopAccountBridge } from "./useDesktopAccountBridge";

/**
 * Account authentication is the desktop front door. Once it succeeds, this
 * bridge quietly creates (or verifies) the revocable per-computer key needed
 * for local roots and signed leases. The old handoff-code ceremony is not a
 * user workflow; only conflicting or unreadable local state needs a decision.
 */
export function DesktopAccountBridge({ children }: { children: React.ReactNode }) {
  const bridge = useDesktopAccountBridge();

  if (bridge.state === "checking") return <AuthSplash />;
  if (bridge.state === "ready") return <>{children}</>;

  return (
    <AuthCard
      title={bridge.state === "replace" ? "Connect this computer" : "Desktop connection unavailable"}
      lead="Your Boltrig account is signed in. Local access uses a separate, revocable key for this computer."
    >
      <div className="auth-handoff">
        <p role="alert" className="auth-error">{bridge.reason}</p>
        <p>
          Connecting stores the private key in the OS keychain. Files and
          background actions remain unavailable until you choose a folder and
          enable them in Settings.
        </p>
        <div className="button-row">
          <button
            type="button"
            className="primary-button"
            disabled={bridge.busy}
            onClick={() => void (bridge.state === "replace" ? bridge.replace() : bridge.connect())}
          >
            {bridge.busy ? "Connecting…" : bridge.state === "replace" ? "Replace local connection" : "Try again"}
          </button>
          <button
            type="button"
            className="secondary-button"
            disabled={bridge.busy}
            onClick={() => bridge.setState("ready")}
          >
            Continue without local access
          </button>
        </div>
      </div>
    </AuthCard>
  );
}
