import type { CharacterId } from "../../character";
import { configuredDesktopDownloadUrl } from "../../desktopDownload";
import { companionName } from "./companionCatalogue";

export function ReadyStep({ character, userName }: { character: CharacterId; userName: string }) {
  const name = companionName(character);
  const downloadUrl = configuredDesktopDownloadUrl();
  return (
    <div className="onboarding-step ready-step">
      <div className="ready-mark onboarding-rise" aria-hidden="true"><span>✓</span></div>
      <div className="onboarding-heading onboarding-rise" style={{ "--onboarding-delay": "80ms" } as React.CSSProperties}>
        <p className="onboarding-kicker">Setup complete</p>
        <h1>You’re ready, {userName}. Meet {name}.</h1>
        <p>You can keep using Boltrig in your browser or bring it onto this computer.</p>
      </div>
      <section
        className="ready-desktop onboarding-rise"
        style={{ "--onboarding-delay": "160ms" } as React.CSSProperties}
      >
        <span className="ready-desktop-icon" aria-hidden="true">
          <svg fill="none" viewBox="0 0 24 24">
            <rect height="13" rx="2" width="18" x="3" y="3.5" />
            <path d="M2 19.5h20M9 16.5v3M15 16.5v3" />
          </svg>
        </span>
        <div className="ready-desktop-copy">
          <h2>Use {name} on this computer</h2>
          <p>Download Boltrig Desktop so {name} can run and take approved actions locally on your personal computer. You choose which files, folders and apps it can use.</p>
          <small>Optional — you can continue in the browser instead.</small>
        </div>
        {downloadUrl ? (
          <a
            className="ready-download-button"
            href={downloadUrl}
            rel="noreferrer"
            target="_blank"
          >
            Download Boltrig Desktop
            <span aria-hidden="true">↗</span>
          </a>
        ) : (
          <p className="ready-download-unavailable">
            The desktop download is not available from this server yet. You can add it later in Settings.
          </p>
        )}
      </section>
    </div>
  );
}
