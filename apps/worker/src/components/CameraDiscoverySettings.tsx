import { useEffect, useState } from "react";

import {
  type DesktopCamera,
  type DesktopCameraDiscoveryStatus,
  desktopCameraDiscover,
  desktopCameraStatus,
  hasDesktopRuntime,
  listenDesktopCameraDiscovery,
  verifyDesktopCameraPtz,
  verifyDesktopCameraSnapshot,
} from "../desktop";

function capabilitySummary(camera: DesktopCamera): string {
  const proven = Object.entries(camera.capabilities)
    .filter(([, capability]) => capability.state === "proven")
    .map(([name]) => name);
  return proven.length > 0 ? proven.join(", ") : "No capabilities proven locally";
}

export function CameraDiscoverySettings() {
  const desktop = hasDesktopRuntime();
  const [status, setStatus] = useState<DesktopCameraDiscoveryStatus | null>(null);
  const [selected, setSelected] = useState<DesktopCamera | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  function applyStatus(value: DesktopCameraDiscoveryStatus | null) {
    if (!value) return;
    setStatus(value);
    setSelected((current) => value.cameras.find((camera) => camera.camera_id === current?.camera_id) ?? value.cameras[0] ?? null);
  }

  function refresh() {
    if (!desktop) return;
    void desktopCameraStatus().then(applyStatus).catch(() => setMessage("Native camera discovery is unavailable."));
  }

  useEffect(() => {
    refresh();
    if (!desktop) return;
    let active = true;
    let unlisten = () => {};
    void listenDesktopCameraDiscovery((value) => {
      if (!active) return;
      applyStatus(value);
    }).then((dispose) => {
      if (active) unlisten = dispose;
      else dispose();
    });
    return () => {
      active = false;
      unlisten();
    };
  }, [desktop]);

  async function verify(kind: "snapshot" | "ptz") {
    if (!selected || busy) return;
    setBusy(true);
    setMessage("");
    try {
      const result = kind === "snapshot"
        ? await verifyDesktopCameraSnapshot(selected.camera_id)
        : await verifyDesktopCameraPtz(selected.camera_id);
      setMessage(`${kind} verification: ${result.state}. ${result.errors.join(" ")}`);
    } catch {
      setMessage(`${kind} verification could not run.`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="settings-card" aria-label="Camera discovery">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Camera discovery</p>
          <h2>{desktop ? "Local cameras" : "Desktop camera discovery"}</h2>
        </div>
        {desktop && <button className="secondary-button" onClick={() => void desktopCameraDiscover().then(applyStatus)} disabled={busy}>Refresh</button>}
      </div>
      {!desktop && <p>Camera inventory is available in the signed desktop Worker only.</p>}
      {desktop && status && (
        <>
          <p>{status.cameras.length} camera{status.cameras.length === 1 ? "" : "s"} · {status.state}</p>
          {status.cameras.length === 0 && <p className="row-meta">No video devices are currently enumerated.</p>}
          <div className="settings-list">
            {status.cameras.map((camera) => (
              <button
                className="list-row"
                key={camera.camera_id}
                onClick={() => setSelected(camera)}
                aria-pressed={selected?.camera_id === camera.camera_id}
              >
                <span><strong>{camera.label}</strong><small>{camera.product} · {camera.transport}</small></span>
                <span className="row-meta">{camera.permission}</span>
              </button>
            ))}
          </div>
          {selected && (
            <div className="settings-card camera-evidence-card">
              <p className="eyebrow">Evidence</p>
              <h3>{selected.label}</h3>
              <p>{capabilitySummary(selected)}</p>
              <p className="row-meta">Formats advertised: {selected.format_count} · ID: <code>{selected.camera_id}</code></p>
              <div className="inline-actions">
                <button className="secondary-button" onClick={() => void verify("snapshot")} disabled={busy}>Verify one frame</button>
                <button className="secondary-button" onClick={() => void verify("ptz")} disabled={busy}>Verify PTZ path</button>
              </div>
              {selected.warnings.map((warning) => <p className="row-meta" key={warning}>{warning}</p>)}
            </div>
          )}
        </>
      )}
      {message && <p role="status">{message}</p>}
    </section>
  );
}
