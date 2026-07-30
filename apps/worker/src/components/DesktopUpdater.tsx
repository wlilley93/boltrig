import { useEffect, useState } from "react";

import {
  type DesktopUpdateCheck,
  type DesktopUpdateReadiness,
  checkDesktopUpdate,
  desktopUpdateReadiness,
  installDesktopUpdate,
  restartDesktopAfterUpdate,
} from "../desktop";

type UpdatePhase =
  | "loading"
  | "unavailable"
  | "ready"
  | "checking"
  | "current"
  | "available"
  | "downloading"
  | "installing"
  | "restart_ready"
  | "error";

export function DesktopUpdater() {
  const [readiness, setReadiness] =
    useState<DesktopUpdateReadiness | null>(null);
  const [update, setUpdate] = useState<DesktopUpdateCheck | null>(null);
  const [phase, setPhase] = useState<UpdatePhase>("loading");
  const [downloaded, setDownloaded] = useState(0);
  const [contentLength, setContentLength] = useState<number | null>(null);
  const [message, setMessage] = useState("");

  useEffect(() => {
    let active = true;
    void desktopUpdateReadiness()
      .then((result) => {
        if (!active) return;
        setReadiness(result);
        setPhase(result.state === "ready" ? "ready" : "unavailable");
      })
      .catch(() => {
        if (!active) return;
        setPhase("unavailable");
        setMessage("Native update readiness could not be verified.");
      });
    return () => {
      active = false;
    };
  }, []);

  async function check() {
    if (phase === "checking") return;
    setPhase("checking");
    setMessage("");
    try {
      const result = await checkDesktopUpdate();
      setUpdate(result);
      if (result.status === "available" && result.version) {
        setPhase("available");
        setMessage(`Signed update ${result.version} is available.`);
      } else {
        setPhase("current");
        setMessage("This desktop is on the latest signed release.");
      }
    } catch {
      setPhase("error");
      setMessage(
        "The signed update service could not be checked. No package was downloaded.",
      );
    }
  }

  async function install() {
    if (!update?.version || phase !== "available") return;
    setPhase("downloading");
    setDownloaded(0);
    setContentLength(null);
    setMessage(`Downloading signed update ${update.version}…`);
    try {
      await installDesktopUpdate(update.version, (event) => {
        if (event.event === "started") {
          setPhase("downloading");
          setContentLength(event.content_length);
          return;
        }
        if (event.event === "progress") {
          setDownloaded((current) => current + event.chunk_length);
          return;
        }
        setPhase("installing");
        setMessage("Download complete. Verifying and installing the update…");
      });
      setPhase("restart_ready");
      setMessage(
        "The signed update is installed. Restart Worker to run the new release.",
      );
    } catch {
      setPhase("error");
      setMessage(
        "The update was not installed. Worker will keep running the current version.",
      );
    }
  }

  async function restart() {
    setMessage("Restarting Worker…");
    try {
      await restartDesktopAfterUpdate();
    } catch {
      setPhase("error");
      setMessage("Worker could not restart automatically. Restart it manually.");
    }
  }

  const busy = phase === "checking"
    || phase === "downloading"
    || phase === "installing";
  const progress = contentLength && contentLength > 0
    ? Math.min(100, Math.round((downloaded / contentLength) * 100))
    : null;

  return (
    <section className="settings-card desktop-updater" aria-label="Desktop updates">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Desktop updates</p>
          <h2>{updateHeading(phase)}</h2>
        </div>
        <span className="row-meta">
          {readiness?.current_version
            ? `v${readiness.current_version}`
            : readiness?.runtime === "web" ? "browser" : "checking"}
        </span>
      </div>
      {readiness?.state === "ready" && (
        <dl className="fact-grid">
          <div><dt>Release service</dt><dd>{readiness.endpoint_origin}</dd></div>
          <div><dt>Target</dt><dd>{readiness.target}</dd></div>
          <div>
            <dt>Verification key</dt>
            <dd>{readiness.public_key_fingerprint?.slice(0, 16)}…</dd>
          </div>
        </dl>
      )}
      {phase === "unavailable" && (
        <p className="notice">
          {readiness?.runtime === "web"
            ? "Desktop updates are unavailable in a browser. Use the signed Worker desktop app."
            : "This desktop build has no complete signed update endpoint and public key configuration."}
        </p>
      )}
      {(phase === "downloading" || phase === "installing") && (
        <div role="status">
          <progress
            aria-label="Update download progress"
            max={100}
            value={progress ?? undefined}
          />
          <p className="muted small">
            {phase === "installing"
              ? "Verifying and installing package…"
              : progress === null
                ? `${downloaded.toLocaleString()} bytes downloaded`
                : `${progress}% downloaded`}
          </p>
        </div>
      )}
      {update?.status === "available" && (
        <div className="result-receipt">
          <strong>Version {update.version}</strong>
          {update.published_at && <small>Published {update.published_at}</small>}
          {update.notes && <p>{update.notes}</p>}
        </div>
      )}
      <div className="inline-actions">
        {readiness?.state === "ready"
          && !["available", "downloading", "installing", "restart_ready"].includes(phase)
          && (
            <button
              className="secondary-button"
              disabled={busy}
              onClick={() => void check()}
            >
              {phase === "checking" ? "Checking…" : "Check for updates"}
            </button>
          )}
        {phase === "available" && (
          <button className="primary-button" onClick={() => void install()}>
            Download, verify and install
          </button>
        )}
        {phase === "restart_ready" && (
          <button className="primary-button" onClick={() => void restart()}>
            Restart Worker
          </button>
        )}
      </div>
      {message && <p className="notice" role="status">{message}</p>}
    </section>
  );
}

function updateHeading(phase: UpdatePhase): string {
  if (phase === "loading") return "Checking release trust…";
  if (phase === "unavailable") return "Updates unavailable";
  if (phase === "checking") return "Checking for updates…";
  if (phase === "current") return "Worker is current";
  if (phase === "available") return "Update available";
  if (phase === "downloading") return "Downloading update";
  if (phase === "installing") return "Installing update";
  if (phase === "restart_ready") return "Restart required";
  if (phase === "error") return "Update did not complete";
  return "Signed release channel";
}
