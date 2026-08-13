import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  EnrolledDevice,
  OwnerDeviceLease,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../client";
import {
  type DesktopDeviceStatus,
  type DesktopLeaseTerminal,
  hasDesktopRuntime,
  listenDeviceLeaseTerminals,
  materializeArtifact,
  stageDesktopWrite,
  takeDesktopReadResult,
} from "../desktop";

type DeviceVerb = "device.file.read" | "device.file.write" | "device.command.run";

interface PreparedAction {
  verb: DeviceVerb;
  params: Record<string, unknown>;
  idempotencyKey: string;
  suggestedName: string;
  writeBytes?: Uint8Array;
}

interface PendingAction extends PreparedAction {
  approvalId: string;
}

interface LocalReadResult {
  leaseId: string;
  bytes: Uint8Array;
  suggestedName: string;
}

interface DeviceActionSessionState {
  pending: PendingAction | null;
  issued: Map<string, PreparedAction>;
  readResults: Map<string, LocalReadResult>;
}

// Exact retry inputs, staged write bytes and recovered read bytes may outlive a
// React mount, but never this renderer process. They are deliberately absent
// from browser storage and the server projection.
const actionSessionState = new Map<string, DeviceActionSessionState>();

function sessionState(deviceId: string): DeviceActionSessionState {
  let state = actionSessionState.get(deviceId);
  if (!state) {
    state = {
      pending: null,
      issued: new Map(),
      readResults: new Map(),
    };
    actionSessionState.set(deviceId, state);
  }
  return state;
}

export function clearLocalDeviceActionSession(
  deviceId?: string,
  rootId?: string,
): void {
  if (!deviceId) {
    actionSessionState.clear();
    return;
  }
  if (!rootId) {
    actionSessionState.delete(deviceId);
    return;
  }
  // Root-scoped clearing mutates the entry in place: a mounted panel holds
  // this object, and replacing or deleting it would orphan the live reference
  // while destroying retained state for the device's other roots.
  const state = actionSessionState.get(deviceId);
  if (!state) return;
  if (String(state.pending?.params.root_id ?? "") === rootId) {
    state.pending = null;
  }
  for (const [leaseId, action] of state.issued) {
    if (String(action.params.root_id ?? "") === rootId) {
      state.issued.delete(leaseId);
    }
  }
}

export function LocalDeviceActions({
  device,
  nativeStatus,
}: {
  device: EnrolledDevice;
  nativeStatus: DesktopDeviceStatus | null;
}) {
  const desktop = hasDesktopRuntime();
  const nativeOperational = nativeStatus !== null && [
    "enrolled",
    "online",
    "degraded",
    "receipt_pending",
    "lease_refused",
  ].includes(nativeStatus.state);
  const localDevice = desktop
    && nativeOperational
    && nativeStatus?.device_id === device.id;
  const boundRoots = useMemo(
    () => device.roots.filter((root) => nativeStatus?.root_ids.includes(root.id)),
    [device.roots, nativeStatus?.root_ids],
  );
  const [verb, setVerb] = useState<DeviceVerb>("device.file.read");
  const eligibleRoots = useMemo(
    () => boundRoots.filter((root) => (
      verb === "device.file.write"
        ? root.scope === "read_write"
        : verb === "device.command.run"
          ? root.command_enabled
          : true
    )),
    [boundRoots, verb],
  );
  const [rootId, setRootId] = useState("");
  const [relativePath, setRelativePath] = useState("");
  const [maxBytes, setMaxBytes] = useState(1_048_576);
  const [writeFile, setWriteFile] = useState<File | null>(null);
  const [overwrite, setOverwrite] = useState(false);
  const [argv, setArgv] = useState('[\"git\", \"status\", \"--short\"]');
  const [cwd, setCwd] = useState("");
  const [timeoutSeconds, setTimeoutSeconds] = useState(30);
  const session = useMemo(() => sessionState(device.id), [device.id]);
  const [pending, setPending] = useState<PendingAction | null>(
    () => session.pending,
  );
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [terminal, setTerminal] = useState<DesktopLeaseTerminal | null>(null);
  const [leaseHistory, setLeaseHistory] = useState<OwnerDeviceLease[]>([]);
  const [readResult, setReadResult] = useState<LocalReadResult | null>(
    () => [...session.readResults.values()][0] ?? null,
  );
  const attemptedReadRecovery = useRef(new Set<string>());

  useEffect(() => {
    if (!eligibleRoots.some((root) => root.id === rootId)) {
      setRootId(eligibleRoots[0]?.id ?? "");
    }
  }, [eligibleRoots, rootId]);

  const recoverRead = useCallback(async (
    leaseId: string,
    suggestedName: string,
  ) => {
    const remembered = session.readResults.get(leaseId);
    if (remembered) {
      setReadResult(remembered);
      return;
    }
    if (!localDevice || attemptedReadRecovery.current.has(leaseId)) return;
    attemptedReadRecovery.current.add(leaseId);
    try {
      const bytes = await takeDesktopReadResult(leaseId);
      if (!bytes) {
        setMessage(
          "The read completed, but its bounded local result is no longer available.",
        );
        return;
      }
      const result = { leaseId, bytes, suggestedName };
      session.readResults.set(leaseId, result);
      setReadResult(result);
    } catch {
      setMessage(
        "The read completed, but its local result could not be retrieved.",
      );
    }
  }, [localDevice, session]);

  const reconcileLeaseHistory = useCallback(async (
    shouldApply: () => boolean = () => true,
  ): Promise<boolean> => {
    try {
      const response = await client.deviceLeases(device.id);
      if (!shouldApply()) return false;
      setLeaseHistory(response.leases);
      for (const lease of response.leases) {
        if (lease.status === "expired") session.issued.delete(lease.id);
      }
      const latestTerminal = response.leases.find(
        (lease) => lease.status === "completed" || lease.status === "failed",
      );
      if (latestTerminal) {
        const exact = session.issued.get(latestTerminal.id);
        session.issued.delete(latestTerminal.id);
        setTerminal({
          lease_id: latestTerminal.id,
          root_id: latestTerminal.root_id,
          verb: latestTerminal.verb,
          status: latestTerminal.status,
          receipt: { ...(latestTerminal.receipt ?? {}) },
        });
        if (
          latestTerminal.verb === "device.file.read"
          && latestTerminal.status === "completed"
          && latestTerminal.receipt?.reported_local_result_available === true
        ) {
          void recoverRead(
            latestTerminal.id,
            exact?.suggestedName
              ?? `boltrig-read-${latestTerminal.id}.bin`,
          );
        }
      }
      return response.leases.some(
        (lease) => lease.status === "issued" || lease.status === "claimed",
      );
    } catch {
      return false;
    }
  }, [device.id, recoverRead, session]);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      const outstanding = await reconcileLeaseHistory(() => active);
      if (active) {
        timer = setTimeout(poll, outstanding ? 2_000 : 15_000);
      }
    };
    void poll();
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
  }, [reconcileLeaseHistory]);

  useEffect(() => {
    if (!localDevice) return;
    let active = true;
    let unlisten = () => {};
    void listenDeviceLeaseTerminals((event) => {
      if (!active || !device.roots.some((root) => root.id === event.root_id)) return;
      const exact = session.issued.get(event.lease_id);
      session.issued.delete(event.lease_id);
      setTerminal(event);
      setMessage(
        event.status === "completed"
          ? `${labelVerb(event.verb)} completed on the local device.`
          : `${labelVerb(event.verb)} failed on the local device.`,
      );
      if (event.verb === "device.file.read" && event.status === "completed") {
        void recoverRead(
          event.lease_id,
          exact?.suggestedName ?? `boltrig-read-${event.lease_id}.bin`,
        );
      }
      void reconcileLeaseHistory(() => active);
    }).then((dispose) => {
      if (active) unlisten = dispose;
      else dispose();
    });
    return () => {
      active = false;
      unlisten();
    };
  }, [
    device.roots,
    localDevice,
    reconcileLeaseHistory,
    recoverRead,
    session,
  ]);

  async function prepare(): Promise<PreparedAction> {
    if (!rootId) throw new Error("Choose a locally bound root.");
    const common = { device_id: device.id, root_id: rootId };
    if (verb === "device.file.read") {
      if (!relativePath.trim()) throw new Error("Enter a root-relative path.");
      if (!Number.isSafeInteger(maxBytes) || maxBytes < 1 || maxBytes > 104_857_600) {
        throw new Error("Maximum bytes must be between 1 and 104,857,600.");
      }
      return {
        verb,
        params: { ...common, relative_path: relativePath.trim(), max_bytes: maxBytes },
        idempotencyKey: crypto.randomUUID(),
        suggestedName: leafName(relativePath),
      };
    }
    if (verb === "device.file.write") {
      if (!relativePath.trim() || !writeFile) {
        throw new Error("Choose a file and enter its root-relative destination.");
      }
      const bytes = new Uint8Array(await writeFile.arrayBuffer());
      const staged = await stageDesktopWrite(bytes);
      return {
        verb,
        params: {
          ...common,
          relative_path: relativePath.trim(),
          content_digest: staged.content_digest,
          byte_size: staged.byte_size,
          overwrite,
        },
        idempotencyKey: crypto.randomUUID(),
        suggestedName: leafName(relativePath),
        writeBytes: bytes,
      };
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(argv);
    } catch {
      throw new Error("Argv must be a JSON array of strings.");
    }
    if (
      !Array.isArray(parsed)
      || parsed.length === 0
      || parsed.length > 64
      || parsed.some((part) => typeof part !== "string" || !part)
    ) {
      throw new Error("Argv must contain 1–64 non-empty strings.");
    }
    if (!Number.isSafeInteger(timeoutSeconds) || timeoutSeconds < 1 || timeoutSeconds > 300) {
      throw new Error("Timeout must be between 1 and 300 seconds.");
    }
    return {
      verb,
      params: {
        ...common,
        argv: parsed,
        cwd_relative: cwd.trim() || null,
        timeout_seconds: timeoutSeconds,
      },
      idempotencyKey: crypto.randomUUID(),
      suggestedName: "command-receipt.json",
    };
  }

  async function dispatch() {
    if (!localDevice || busy) return;
    setBusy(true);
    setMessage("");
    setTerminal(null);
    try {
      const action = pending ?? await prepare();
      if (pending?.writeBytes) {
        const staged = await stageDesktopWrite(pending.writeBytes);
        if (
          staged.content_digest !== pending.params.content_digest
          || staged.byte_size !== pending.params.byte_size
        ) {
          throw new Error("The locally staged write no longer matches the approved action.");
        }
      }
      const result = await client.invoke({
        noun: "device",
        verb: action.verb,
        params: action.params,
        idempotency_key: action.idempotencyKey,
        ...(pending ? { approval_id: pending.approvalId } : {}),
      });
      if (result.status === "pending_human") {
        const retained = { ...action, approvalId: result.hitl_request_id };
        session.pending = retained;
        setPending(retained);
        setMessage(
          `Exact action ${result.hitl_request_id} needs an independent approval in the originating chat. `
          + "After it is approved, retry this unchanged action.",
        );
        return;
      }
      if (
        result.status === "denied"
        || result.status === "error"
        || result.status === "unavailable"
      ) {
        // The SDK synthesizes denied (401/403) and unavailable (transport)
        // receipts for failures the dispatcher never processed. The single-use
        // approval is then still unconsumed; discarding it here would strand a
        // granted originating chat decision, so keep the exact action retryable until the
        // kernel confirms the approval is spent.
        if (
          pending
          && result.status !== "error"
          && await approvalStillRedeemable(pending.approvalId)
        ) {
          setMessage(
            `The approved action was not applied: ${result.reason}. `
            + "Retry this unchanged action.",
          );
          return;
        }
        session.pending = null;
        setPending(null);
        setMessage(`No device lease was issued: ${result.reason}.`);
        return;
      }
      // An approval is single-use once the dispatcher returns anything other
      // than a pause or a synthesized failure receipt; never offer a stale
      // approval id for replay.
      session.pending = null;
      setPending(null);
      const output = result.output;
      if (!isLeaseOutput(
        output,
        action.verb,
        device.id,
        String(action.params.root_id ?? ""),
      )) {
        setMessage("The dispatcher did not return a valid local-device lease receipt.");
        return;
      }
      session.issued.set(output.lease_id, action);
      setMessage(
        result.status === "degraded"
          ? `Lease ${output.lease_id} was returned in degraded state; local execution is not assumed.`
          : `Lease ${output.lease_id} issued. Waiting for the local device receipt.`,
      );
      void reconcileLeaseHistory();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "The local-device action was not submitted.");
    } finally {
      setBusy(false);
    }
  }

  async function saveRead() {
    if (!readResult || busy) return;
    setBusy(true);
    try {
      const result = await materializeArtifact(
        readResult.suggestedName,
        readResult.bytes,
      );
      setMessage(
        result.status === "saved"
          ? "The local read result was saved through the native file dialog."
          : result.status === "cancelled"
            ? "Save cancelled."
            : "Native save is unavailable outside the desktop app.",
      );
      if (result.status === "saved") {
        session.readResults.delete(readResult.leaseId);
        setReadResult(null);
      }
    } catch {
      setMessage("The local read result was not saved.");
    } finally {
      setBusy(false);
    }
  }

  const controlsDisabled = !localDevice || eligibleRoots.length === 0 || busy || pending !== null;
  return (
    <section className="settings-card author-form device-action-panel">
      <div className="section-heading">
        <div><p className="eyebrow">Local actions</p><h2>Run through the governed dispatcher</h2></div>
        <span className="row-meta">{localDevice ? "this device" : desktop ? "remote device" : "browser only"}</span>
      </div>
      {!desktop && (
        <p className="notice">Local file and command controls require the signed Worker desktop app. This browser cannot execute them.</p>
      )}
      {desktop && !localDevice && (
        <p className="notice">This is not the computer connected to the local native agent. Remote actions are view-only here.</p>
      )}
      {localDevice && eligibleRoots.length === 0 && (
        <p className="notice">No locally bound root supports this action. Bind an eligible root on this device first.</p>
      )}
      <div className="author-grid">
        <label><span>Action</span><select className="field-control" aria-label="Local action" value={verb} disabled={!localDevice || busy || pending !== null} onChange={(event) => setVerb(event.target.value as DeviceVerb)}><option value="device.file.read">Read file</option><option value="device.file.write">Write file</option><option value="device.command.run">Run argv command</option></select></label>
        <label><span>Native root</span><select className="field-control" aria-label="Native root" value={rootId} disabled={controlsDisabled} onChange={(event) => setRootId(event.target.value)}>{eligibleRoots.map((root) => <option value={root.id} key={root.id}>{root.label}</option>)}</select></label>
      </div>
      {verb === "device.file.read" && (
        <div className="author-grid">
          <label><span>Root-relative path</span><input className="field-control" value={relativePath} disabled={controlsDisabled} onChange={(event) => setRelativePath(event.target.value)} placeholder="reports/final.txt" /></label>
          <label><span>Maximum bytes</span><input className="field-control" type="number" min={1} max={104_857_600} value={maxBytes} disabled={controlsDisabled} onChange={(event) => setMaxBytes(Number(event.target.value))} /></label>
        </div>
      )}
      {verb === "device.file.write" && (
        <div className="author-grid">
          <label><span>Root-relative destination</span><input className="field-control" value={relativePath} disabled={controlsDisabled} onChange={(event) => setRelativePath(event.target.value)} placeholder="reports/result.txt" /></label>
          <label><span>Local payload</span><input className="field-control" aria-label="Local payload" type="file" disabled={controlsDisabled} onChange={(event) => setWriteFile(event.target.files?.[0] ?? null)} /></label>
          <label className="check-label"><input type="checkbox" checked={overwrite} disabled={controlsDisabled} onChange={(event) => setOverwrite(event.target.checked)} />Replace an existing regular file</label>
        </div>
      )}
      {verb === "device.command.run" && (
        <>
          <label><span>Argv JSON array — no shell string</span><textarea className="field-control code-field" aria-label="Command argv" rows={3} value={argv} disabled={controlsDisabled} onChange={(event) => setArgv(event.target.value)} /></label>
          <div className="author-grid">
            <label><span>Root-relative working directory (optional)</span><input className="field-control" value={cwd} disabled={controlsDisabled} onChange={(event) => setCwd(event.target.value)} /></label>
            <label><span>Timeout seconds</span><input className="field-control" type="number" min={1} max={300} value={timeoutSeconds} disabled={controlsDisabled} onChange={(event) => setTimeoutSeconds(Number(event.target.value))} /></label>
          </div>
        </>
      )}
      <div className="inline-actions">
        <button className="primary-button" disabled={!localDevice || eligibleRoots.length === 0 || busy} onClick={() => void dispatch()}>
          {pending ? "Retry approved action" : busy ? "Submitting…" : "Request exact-action lease"}
        </button>
        {pending && <button className="secondary-button" disabled={busy} onClick={() => { session.pending = null; setPending(null); setMessage("Local retry cleared. The originating chat request was not withdrawn."); }}>Clear local retry</button>}
      </div>
      {message && <p className="notice" role="status">{message}</p>}
      {pending && (
        <p className="muted">
          This exact retry exists only in renderer memory; a full reload clears it.
        </p>
      )}
      {terminal && (
        <div className="result-receipt">
          <strong>{terminal.status === "completed" ? "Local receipt" : "Local failure receipt"}</strong>
          <small>{terminal.lease_id} · {terminal.verb}</small>
          <code>{JSON.stringify(terminal.receipt)}</code>
        </div>
      )}
      {leaseHistory.length > 0 && (
        <div className="result-receipt">
          <strong>Owner-visible lease history</strong>
          {leaseHistory.slice(0, 5).map((lease) => (
            <small key={lease.id}>
              {lease.id} · {labelVerb(lease.verb)} · {lease.status}
              {lease.settled_at ? ` · ${new Date(lease.settled_at).toLocaleString()}` : ""}
            </small>
          ))}
        </div>
      )}
      {leaseHistory.some((lease) => lease.status === "expired") && (
        <p className="muted">
          Expired means the lease or receipt window ended; it does not prove a
          claimed native action never ran.
        </p>
      )}
      {readResult && (
        <>
          <div className="inline-actions">
            <span className="muted">{readResult.bytes.byteLength.toLocaleString()} local bytes ready</span>
            <button className="secondary-button" disabled={busy} onClick={() => void saveRead()}>Save local read…</button>
            <button className="secondary-button" disabled={busy} onClick={() => { session.readResults.delete(readResult.leaseId); setReadResult(null); }}>Discard</button>
          </div>
          <p className="muted">
            Save before reloading; read bytes are deliberately not persisted.
          </p>
        </>
      )}
    </section>
  );
}

async function approvalStillRedeemable(approvalId: string): Promise<boolean> {
  try {
    const approval = await client.invokeApprovalState(approvalId);
    return approval.status === "approved" || approval.status === "pending";
  } catch {
    // The kernel is unreachable; nothing proves the approval was consumed,
    // so keep the exact action for retry.
    return true;
  }
}

function isLeaseOutput(
  value: unknown,
  verb: DeviceVerb,
  deviceId: string,
  rootId: string,
): value is { status: "leased"; lease_id: string } {
  if (!value || typeof value !== "object") return false;
  const output = value as Record<string, unknown>;
  return output.status === "leased"
    && typeof output.lease_id === "string"
    && output.lease_id.length > 0
    && output.verb === verb
    && output.device_id === deviceId
    && output.root_id === rootId;
}

function leafName(path: string): string {
  return path.split("/").filter(Boolean).at(-1) ?? "local-result.bin";
}

function labelVerb(verb: string): string {
  if (verb === "device.file.read") return "Read";
  if (verb === "device.file.write") return "Write";
  if (verb === "device.command.run") return "Command";
  return "Device action";
}
