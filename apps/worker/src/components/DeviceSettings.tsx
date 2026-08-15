import { useEffect, useState } from "react";
import {
  BoltrigApiError,
  type DeviceRootResponse,
  type EnrolledDevice,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../client";
import { configuredDesktopDownloadUrl } from "../desktopDownload";
import {
  type DesktopDeviceStatus,
  bindDesktopRoot,
  clearDesktopSession,
  desktopDeviceStatus,
  hasDesktopRuntime,
  listenDesktopDeviceStatus,
  unbindDesktopRoot,
} from "../desktop";
import {
  DEFAULT_DESKTOP_LABEL,
  connectAuthenticatedDesktop,
} from "../desktopTrust";
import {
  LocalDeviceActions,
  clearLocalDeviceActionSession,
} from "./LocalDeviceActions";
import {
  desktopConnectionVisible,
  needsLocalEnrollmentCleanup,
  trustedComputersVisible,
} from "./deviceSettingsVisibility";
export function DeviceSettings() {
  const desktop = hasDesktopRuntime();
  const [devices, setDevices] = useState<EnrolledDevice[]>([]);
  const [devicesLoaded, setDevicesLoaded] = useState(false);
  const [nativeStatus, setNativeStatus] = useState<DesktopDeviceStatus | null>(null);
  const [available, setAvailable] = useState(true);
  const [devicesError, setDevicesError] = useState("");
  const [busy, setBusy] = useState(false);
  const [label, setLabel] = useState(DEFAULT_DESKTOP_LABEL);
  const [selected, setSelected] = useState<string | null>(null);
  const [rootLabel, setRootLabel] = useState("");
  const [rootScope, setRootScope] = useState<"read" | "read_write">("read");
  const [commands, setCommands] = useState(false);
  const [armed, setArmed] = useState("");
  const [message, setMessage] = useState("");

  function refresh() {
    void client.devices()
      .then((result) => {
        setDevices(result.devices);
        setAvailable(true);
        setDevicesError("");
        setDevicesLoaded(true);
        setSelected((current) => (
          current && result.devices.some((item) => item.id === current)
            ? current
            : result.devices[0]?.id ?? null
        ));
      })
      .catch((reason) => {
        // Only a kernel refusal proves trusted computers are not enabled; a transport
        // failure says nothing about the deployment and must stay retryable.
        if (
          reason instanceof BoltrigApiError
          && (reason.status === 403 || reason.status === 404)
        ) {
          setAvailable(false);
          setDevicesError("");
        } else {
          setDevicesError("Devices could not be loaded. The kernel was unreachable.");
        }
        setDevicesLoaded(true);
      });
  }

  function refreshNative() {
    if (!desktop) {
      setNativeStatus(null);
      return;
    }
    void desktopDeviceStatus()
      .then(setNativeStatus)
      .catch(() => setNativeStatus({
        state: "reenrollment_required",
        device_id: null,
        root_ids: [],
        reason: "native_status_unavailable",
      }));
  }

  useEffect(refresh, []);
  useEffect(() => {
    refreshNative();
    if (!desktop) return;
    let active = true;
    let unlisten = () => {};
    void listenDesktopDeviceStatus((status) => {
      if (!active) return;
      setNativeStatus(status);
      refresh();
    }).then((dispose) => {
      if (active) unlisten = dispose;
      else dispose();
    });
    return () => {
      active = false;
      unlisten();
    };
  }, [desktop]);

  async function connectDesktop() {
    if (!desktop || busy) return;
    setBusy(true);
    setMessage("");
    try {
      const completed = await connectAuthenticatedDesktop(label.trim());
      setSelected(completed.device_id);
      setMessage(
        `${completed.label} is connected to this account. Its private key stays in the OS keychain.`,
      );
      refreshNative();
      refresh();
    } catch {
      setMessage("This computer could not be connected. No local trust key was changed.");
    } finally {
      setBusy(false);
    }
  }

  async function createRoot() {
    if (!selected || busy || nativeStatus?.device_id !== selected || !desktop) return;
    setBusy(true);
    setMessage("");
    try {
      const result = await client.createDeviceRoot(selected, {
        label: rootLabel.trim(),
        scope: rootScope,
        command_enabled: commands,
        git_enabled: false,
      });
      if (!isDeviceRootResponse(result)) {
        setMessage("reason" in result && typeof result.reason === "string" ? result.reason : "The root was not registered.");
        return;
      }
      try {
        const bound = await bindDesktopRoot(
          result.root.id,
          result.root.scope,
          result.root.command_enabled,
        );
        if (!bound) throw new Error("native_root_selection_cancelled");
      } catch {
        const rollback = await client.revokeDeviceRoot(selected, result.root.id)
          .catch(() => ({ status: "error", reason: "rollback_failed" }));
        let localCleanup = true;
        try {
          await unbindDesktopRoot(result.root.id);
        } catch {
          localCleanup = false;
        }
        setMessage(
          rollback.status === "ok" && localCleanup
            ? "Native folder selection was cancelled or failed; the server root was rolled back."
            : rollback.status !== "ok"
              ? "Native binding failed and server rollback also failed. Revoke the unbound root before retrying."
              : "Server root rolled back, but local keychain cleanup needs to be retried on this desktop.",
        );
        refresh();
        refreshNative();
        return;
      }
      setRootLabel("");
      setCommands(false);
      setMessage("Local folder bound to an opaque root. Its native path never left this device.");
      refresh();
      refreshNative();
    } catch {
      setMessage("The local root was not registered.");
    } finally {
      setBusy(false);
    }
  }

  async function revokeRoot(deviceId: string, rootId: string) {
    const key = `root:${rootId}`;
    if (armed !== key) {
      setArmed(key);
      return;
    }
    if (busy) return;
    setBusy(true);
    try {
      const result = await client.revokeDeviceRoot(deviceId, rootId);
      if (result.status !== "ok") {
        setMessage(result.reason ?? result.status);
        return;
      }
      clearLocalDeviceActionSession(deviceId, rootId);
      let localRemoved = true;
      if (desktop && nativeStatus?.device_id === deviceId && nativeStatus.root_ids.includes(rootId)) {
        try {
          await unbindDesktopRoot(rootId);
        } catch {
          localRemoved = false;
        }
      }
      setMessage(
        localRemoved
          ? "Device root revoked and its local binding removed."
          : "Server root revoked. Local keychain cleanup needs to be retried on this desktop.",
      );
      refresh();
      refreshNative();
    } catch {
      setMessage("The device root was not revoked.");
    } finally {
      setArmed("");
      setBusy(false);
    }
  }

  async function revokeDevice(deviceId: string) {
    const key = `device:${deviceId}`;
    if (armed !== key) {
      setArmed(key);
      return;
    }
    if (busy) return;
    setBusy(true);
    try {
      const result = await client.revokeDevice(deviceId);
      if (result.status !== "ok") {
        setMessage(result.reason ?? result.status);
        return;
      }
      clearLocalDeviceActionSession(deviceId);
      let localCleared = true;
      if (desktop && nativeStatus?.device_id === deviceId) {
        try {
          await clearDesktopSession();
        } catch {
          localCleared = false;
        }
      }
      setMessage(
        localCleared
          ? "Computer trust, active roots, and matching local credentials were revoked."
          : "Device authority was revoked on the server. Local keychain cleanup will retry when the agent observes revocation.",
      );
      setSelected(null);
      refresh();
      refreshNative();
    } catch {
      setMessage("The device was not revoked.");
    } finally {
      setArmed("");
      setBusy(false);
    }
  }

  async function removeOrphanedLocalRoot(rootId: string) {
    const key = `local-root:${rootId}`;
    if (armed !== key) {
      setArmed(key);
      return;
    }
    if (busy) return;
    setBusy(true);
    setMessage("");
    try {
      await unbindDesktopRoot(rootId);
      setMessage(
        `Local binding ${rootId} was removed. No server root was changed.`,
      );
      refreshNative();
    } catch {
      setMessage(
        `Local binding ${rootId} could not be removed from the OS keychain. It is safe to retry.`,
      );
    } finally {
      setArmed("");
      setBusy(false);
    }
  }

  async function clearOrphanedLocalEnrollment() {
    const key = "local-enrollment";
    if (armed !== key) {
      setArmed(key);
      return;
    }
    if (busy) return;
    setBusy(true);
    setMessage("");
    try {
      await clearDesktopSession();
      if (nativeStatus?.device_id) {
        clearLocalDeviceActionSession(nativeStatus.device_id);
      }
      setMessage(
        "The unreadable or orphaned local credentials were removed. No trusted computer was revoked.",
      );
      refreshNative();
    } catch {
      setMessage(
        "The local credentials could not be removed from the OS keychain. It is safe to retry.",
      );
    } finally {
      setArmed("");
      setBusy(false);
    }
  }

  const device = devices.find((item) => item.id === selected) ?? null;
  const selectedIsLocal = desktop && device?.id === nativeStatus?.device_id;
  const localServerDevice = nativeStatus?.device_id
    ? devices.find((item) => item.id === nativeStatus.device_id) ?? null
    : null;
  const orphanedRootIds = desktop && devicesLoaded && available && localServerDevice
    ? nativeStatus?.root_ids.filter(
      (rootId) => !localServerDevice.roots.some((root) => root.id === rootId),
    ) ?? []
    : [];
  const localEnrollmentNeedsCleanup = needsLocalEnrollmentCleanup({
    available, desktop, devicesLoaded, localServerDevice, nativeStatus,
  });
  const desktopDownloadUrl = configuredDesktopDownloadUrl();
  const localConnectionReady = Boolean(localServerDevice) && !localEnrollmentNeedsCleanup;
  const showDesktopConnection = desktopConnectionVisible(desktop, desktopDownloadUrl);
  const showTrustedComputers = trustedComputersVisible(available, devicesError);
  return (
    <>
      {showDesktopConnection && (
        <DesktopConnectionCard
          available={available}
          busy={busy}
          connected={localConnectionReady}
          desktop={desktop}
          downloadUrl={desktopDownloadUrl}
          label={label}
          needsCleanup={localEnrollmentNeedsCleanup}
          onConnect={() => void connectDesktop()}
          onLabel={setLabel}
        />
      )}
      {desktop && <section className="settings-card">
        <div className="section-heading">
          <div><p className="eyebrow">Native agent</p><h2>This computer’s connection</h2></div>
          <span className="row-meta">{nativeStatus?.state ?? (desktop ? "checking" : "not available")}</span>
        </div>
        {nativeStatus?.device_id ? (
          <p>
            Device <code>{nativeStatus.device_id}</code> · {nativeStatus.root_ids.length} locally bound root{nativeStatus.root_ids.length === 1 ? "" : "s"}.
            {nativeStatus.reason ? ` ${nativeStatus.reason}.` : ""}
          </p>
        ) : nativeStatus?.state === "reenrollment_required" ? (
          <p className="notice">
            The local trust key cannot be read
            {nativeStatus.reason ? ` (${nativeStatus.reason})` : ""}. Account
            sign-in remains active.
          </p>
        ) : (
          <p className="muted">This computer is not connected. Other trusted computers remain view-only here.</p>
        )}
        {orphanedRootIds.map((rootId) => (
          <div className="data-row static" key={rootId}>
            <span className="activity-dot warning" />
            <span className="data-row-copy">
              <strong>Orphaned local root</strong>
              <small><code>{rootId}</code> no longer exists on this server device.</small>
            </span>
            <button
              className={armed === `local-root:${rootId}` ? "danger-button armed" : "danger-button"}
              disabled={busy}
              onClick={() => void removeOrphanedLocalRoot(rootId)}
            >
              {armed === `local-root:${rootId}`
                ? "Confirm local removal"
                : "Remove local binding"}
            </button>
          </div>
        ))}
        {localEnrollmentNeedsCleanup && (
          <div className="auth-handoff">
            <p>
              This local device identity is unreadable or is no longer present
              on this server. Removing it changes only this computer.
            </p>
            <button
              className={armed === "local-enrollment" ? "danger-button armed" : "danger-button"}
              disabled={busy}
              onClick={() => void clearOrphanedLocalEnrollment()}
            >
              {armed === "local-enrollment"
                ? "Confirm local credential removal"
                : "Remove stale local credentials"}
            </button>
          </div>
        )}
      </section>}
      {showTrustedComputers && <section className="settings-card">
        <p className="eyebrow">Trusted computers</p>
        {devicesError ? <p className="muted">{devicesError} <button className="secondary-button" type="button" onClick={refresh}>Retry</button></p> : !available ? <p className="muted">Trusted computers are not enabled on this deployment.</p> : devices.length === 0 ? <p className="muted">No trusted computers.</p> : devices.map((item) => {
          const local = desktop && nativeStatus?.device_id === item.id;
          return (
            <button className={selected === item.id ? "device-row selected" : "device-row"} key={item.id} onClick={() => setSelected(item.id)}>
              <span className={`presence ${item.presence}`} />
              <span>
                <strong>{item.label}{local ? " · this desktop" : ""}</strong>
                <small>{item.availability_mode} · {item.roots.length} roots · {item.public_key_fingerprint.slice(0, 12)}</small>
              </span>
            </button>
          );
        })}
      </section>}
      {device && (
        <section className="settings-card author-form">
          <div className="section-heading"><div><p className="eyebrow">Computer folders</p><h2>{device.label}</h2></div><span className="row-meta">{selectedIsLocal ? "local" : "remote · view only"}</span></div>
          <p>Folders use opaque handles. Native paths stay on the trusted computer; every remote file or command action requires a separately consumed exact-action approval.</p>
          {device.roots.map((root) => {
            const locallyBound = selectedIsLocal && nativeStatus?.root_ids.includes(root.id);
            return (
              <div className="data-row static" key={root.id}>
                <span className={`activity-dot ${locallyBound ? "ok" : device.presence}`} />
                <span className="data-row-copy">
                  <strong>{root.label}</strong>
                  <small>{root.scope.replace("_", " ")} · commands {root.command_enabled ? "enabled" : "off"} · {locallyBound ? "bound on this desktop" : "not bound here"}</small>
                </span>
                <button className={armed === `root:${root.id}` ? "danger-button armed" : "danger-button"} disabled={busy} onClick={() => void revokeRoot(device.id, root.id)}>{armed === `root:${root.id}` ? "Confirm revoke" : "Revoke"}</button>
              </div>
            );
          })}
          {!selectedIsLocal && (
            <p className="notice">
              Folder access is disabled here because this is not the connected local computer.
            </p>
          )}
          <div className="author-grid">
            <label><span>Opaque root label</span><input className="field-control" value={rootLabel} disabled={!selectedIsLocal || busy} onChange={(event) => setRootLabel(event.target.value)} /></label>
            <label><span>Scope</span><select className="field-control" value={rootScope} disabled={!selectedIsLocal || busy} onChange={(event) => setRootScope(event.target.value as typeof rootScope)}><option value="read">Read</option><option value="read_write">Read and write</option></select></label>
            <label className="check-label"><input type="checkbox" checked={commands} disabled={!selectedIsLocal || busy} onChange={(event) => setCommands(event.target.checked)} />Allow the local agent and signed command leases on this root</label>
          </div>
          <button className="primary-button" disabled={!rootLabel.trim() || !selectedIsLocal || busy} onClick={() => void createRoot()}>Register and choose local folder…</button>
          <button className={armed === `device:${device.id}` ? "danger-button armed" : "danger-button"} disabled={busy} onClick={() => void revokeDevice(device.id)}>{armed === `device:${device.id}` ? "Confirm revoke device" : "Revoke device"}</button>
        </section>
      )}
      {device && <LocalDeviceActions key={device.id} device={device} nativeStatus={nativeStatus} />}
      {message && <p className="notice" role="status">{message}</p>}
    </>
  );
}

function DesktopConnectionCard({
  available,
  busy,
  connected,
  desktop,
  downloadUrl,
  label,
  needsCleanup,
  onConnect,
  onLabel,
}: {
  available: boolean;
  busy: boolean;
  connected: boolean;
  desktop: boolean;
  downloadUrl: string | null;
  label: string;
  needsCleanup: boolean;
  onConnect(): void;
  onLabel(value: string): void;
}) {
  const disabled = !label.trim() || !available || busy || connected || needsCleanup;
  return (
    <section className="settings-card author-form">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Boltrig Desktop</p>
          <h2>{desktop ? "This computer" : "Work locally on your computer"}</h2>
        </div>
        <span className="row-meta">{desktop ? "signed app" : "download"}</span>
      </div>
      {desktop ? (
        <>
          <p>Account sign-in is the front door. A revocable computer key stays in the OS keychain.</p>
          <label>
            <span>Computer name</span>
            <input className="field-control" disabled={busy || connected || needsCleanup} onChange={(event) => onLabel(event.target.value)} placeholder={DEFAULT_DESKTOP_LABEL} value={label} />
          </label>
          <button className="primary-button" disabled={disabled} onClick={onConnect}>
            {busy ? "Connecting…" : connected ? "Connected to this account" : "Connect this computer"}
          </button>
          <small>Folders, Bash and background actions stay off until you enable them separately below.</small>
        </>
      ) : (
        <>
          <p>Sign in to the desktop app with this account to run local tasks. No handoff code is required.</p>
          {downloadUrl
            ? <a className="primary-button" href={downloadUrl} rel="noreferrer" target="_blank">Download Boltrig Desktop</a>
            : <p className="notice">A signed desktop download has not been published for this deployment.</p>}
        </>
      )}
    </section>
  );
}

function isDeviceRootResponse(value: unknown): value is DeviceRootResponse {
  if (!value || typeof value !== "object" || !("root" in value)) return false;
  const root = (value as { root?: unknown }).root;
  if (!root || typeof root !== "object") return false;
  const candidate = root as Record<string, unknown>;
  return typeof candidate.id === "string"
    && (candidate.scope === "read" || candidate.scope === "read_write")
    && typeof candidate.command_enabled === "boolean";
}
