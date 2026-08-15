import { useEffect, useState } from "react";
import type { SensingResponse } from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";
import { desktopDeviceStatus } from "../../desktop";
import { desktopCameraStatus, listenDesktopCameraDiscovery } from "../../desktopCamera";
import { SectionHead } from "./SectionHead";
import {
  CameraSettingsGroup,
  CapabilitySettingsGroup,
  PresenceSettingsGroup,
  type CameraChoice,
} from "./SensingSettingsGroups";

// Camera and presence are Boltrig services, not character-owned daemons. A
// character can request either capability, and the kernel refuses it plainly
// when the user has disabled it or its local preconditions are not met.

/** Read the one camera inventory published by the desktop runtime. */
function useDiscoveredCameras(): { deviceId: string | null; cameras: CameraChoice[] } {
  const [deviceId, setDeviceId] = useState<string | null>(null);
  const [cameras, setCameras] = useState<CameraChoice[]>([]);

  useEffect(() => {
    let cancelled = false;
    const read = () => {
      void desktopCameraStatus().then((status) => {
        if (cancelled || !status) return;
        setCameras(status.cameras.map((camera) => ({
          camera_id: camera.camera_id,
          label: camera.label || camera.product || camera.camera_id,
        })));
      }).catch(() => undefined);
    };
    void desktopDeviceStatus()
      .then((status) => { if (!cancelled) setDeviceId(status?.device_id ?? null); })
      .catch(() => undefined);
    read();
    let stop: (() => void) | undefined;
    void listenDesktopCameraDiscovery(read).then((unlisten) => {
      if (cancelled) unlisten?.();
      else stop = unlisten ?? undefined;
    }).catch(() => undefined);
    return () => { cancelled = true; stop?.(); };
  }, []);

  return { cameras, deviceId };
}

function useSensing() {
  const [sensing, setSensing] = useState<SensingResponse | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "unavailable">("loading");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    let cancelled = false;
    if (typeof client.sensing !== "function") {
      setState("unavailable");
      return;
    }
    void client.sensing()
      .then((result) => {
        if (cancelled) return;
        setSensing(result);
        setState("ready");
      })
      .catch(() => { if (!cancelled) setState("unavailable"); });
    return () => { cancelled = true; };
  }, []);

  async function save(
    apply: () => Promise<SensingResponse>,
    optimistic: SensingResponse | null,
    failure: string,
  ) {
    if (busy) return;
    const previous = sensing;
    setBusy(true);
    setMessage("");
    if (optimistic) setSensing(optimistic);
    try {
      const result = await apply();
      if (result.status !== "ok") {
        setSensing(previous);
        setMessage(result.reason ?? failure);
        return;
      }
      setSensing(result);
    } catch {
      setSensing(previous);
      setMessage(failure);
    } finally {
      setBusy(false);
    }
  }

  return { busy, message, save, sensing, setMessage, state };
}

export function SensingSection({
  head = true,
  view = "all",
}: {
  head?: boolean;
  view?: "all" | "presence" | "sight";
}) {
  const { busy, message, save, sensing, setMessage, state } = useSensing();
  const { cameras, deviceId } = useDiscoveredCameras();

  if (state === "loading") return <p className="muted small">Reading your camera settings…</p>;
  if (state === "unavailable" || !sensing) {
    return (
      <>
        {head && <SectionHead section="sensing" />}
        <p className="notice">
          Camera and presence settings could not be read, so nothing here has been changed.
        </p>
      </>
    );
  }

  return (
    <>
      {head && <SectionHead section="sensing" />}
      {view !== "presence" && (
        <CameraSettingsGroup
          busy={busy}
          cameras={cameras}
          compact={view !== "all"}
          deviceId={deviceId}
          save={save}
          sensing={sensing}
        />
      )}
      {view !== "sight" && (
        <PresenceSettingsGroup busy={busy} compact={view !== "all"} save={save} sensing={sensing} />
      )}
      {view === "all" && <CapabilitySettingsGroup decisions={sensing.capabilities} />}
      {message && (
        <p className="notice" role="alert">
          {message}{" "}
          <button className="settings-kit-button" onClick={() => setMessage("")} type="button">
            Dismiss
          </button>
        </p>
      )}
    </>
  );
}
