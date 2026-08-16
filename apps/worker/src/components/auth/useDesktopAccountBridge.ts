import { useCallback, useEffect, useState } from "react";

import { client } from "../../client";
import {
  clearDesktopSession,
  desktopDeviceStatus,
  isDesktop,
} from "../../desktop";
import { connectAuthenticatedDesktop } from "../../desktopTrust";

export type DesktopBridgeState = "checking" | "ready" | "replace" | "unavailable";

type Inspection =
  | { state: "ready" | "connect" }
  | { state: "replace"; reason: string };

async function inspectDesktopConnection(): Promise<Inspection> {
  const local = await desktopDeviceStatus();
  if (!local) return { state: "ready" };
  if (local.state === "reenrollment_required") {
    return { state: "replace", reason: "The local trust key cannot be read and must be replaced." };
  }
  if (!local.device_id) return { state: "connect" };
  try {
    const result = await client.devices();
    return result.devices.some((device) => device.id === local.device_id)
      ? { state: "ready" }
      : {
          state: "replace",
          reason: "This computer is connected to a different or revoked Boltrig account.",
        };
  } catch {
    // Account auth succeeded. A transient device-list failure must not turn
    // the desktop into a sign-in loop or destroy a potentially valid key.
    return { state: "ready" };
  }
}

export function useDesktopAccountBridge() {
  const [state, setState] = useState<DesktopBridgeState>(isDesktop ? "checking" : "ready");
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState("");

  const connect = useCallback(async () => {
    setBusy(true);
    setReason("");
    try {
      await connectAuthenticatedDesktop();
      setState("ready");
    } catch {
      setReason("Your account is signed in, but this computer could not establish its local trust key.");
      setState("unavailable");
    } finally {
      setBusy(false);
    }
  }, []);

  const inspect = useCallback(async () => {
    if (!isDesktop) return setState("ready");
    setState("checking");
    setReason("");
    try {
      const result = await inspectDesktopConnection();
      if (result.state === "connect") return void connect();
      if (result.state === "replace") setReason(result.reason);
      setState(result.state);
    } catch {
      setReason("The desktop keychain could not be checked.");
      setState("replace");
    }
  }, [connect]);

  useEffect(() => {
    void inspect();
  }, [inspect]);

  const replace = useCallback(async () => {
    if (busy) return;
    setBusy(true);
    setReason("");
    try {
      await clearDesktopSession();
    } catch {
      setBusy(false);
      setReason("The old local key could not be removed from the OS keychain.");
      return;
    }
    setBusy(false);
    await connect();
  }, [busy, connect]);

  return { busy, connect, reason, replace, setState, state };
}
