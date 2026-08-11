// @vitest-environment happy-dom

import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  createDeviceRoot: vi.fn(),
  deviceLeases: vi.fn(),
  devices: vi.fn(),
  invoke: vi.fn(),
  revokeDevice: vi.fn(),
  revokeDeviceRoot: vi.fn(),
  startDeviceEnrollment: vi.fn(),
}));

const native = vi.hoisted(() => ({
  bindDesktopRoot: vi.fn(),
  clearDesktopSession: vi.fn(),
  completeDesktopEnrollment: vi.fn(),
  desktopDeviceStatus: vi.fn(),
  hasDesktopRuntime: vi.fn(),
  leaseHandler: null as null | ((event: Record<string, unknown>) => void),
  listenDesktopDeviceStatus: vi.fn(),
  listenDeviceLeaseTerminals: vi.fn(),
  materializeArtifact: vi.fn(),
  serializeDesktopEnrollment: vi.fn((value: unknown) => JSON.stringify(value)),
  stageDesktopWrite: vi.fn(),
  takeDesktopReadResult: vi.fn(),
  unbindDesktopRoot: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));
vi.mock("../src/desktop", () => native);

import { DeviceSettings } from "../src/components/DeviceSettings";
import {
  clearLocalDeviceActionSession,
} from "../src/components/LocalDeviceActions";

const verifier = {
  algorithm: "Ed25519",
  key_id: "a".repeat(64),
  public_key: "pinned-public-key",
};
const enrollment = {
  authorization_code: "one-time-code",
  expires_at: "2030-01-01T00:00:00Z",
  verification_uri: "/#/settings",
  lease_verifier: verifier,
};
const root = {
  id: "root_1",
  label: "Workspace",
  scope: "read_write",
  command_enabled: true,
  git_enabled: false,
};
const device = {
  id: "device_1",
  label: "Office Mac",
  public_key_fingerprint: "f".repeat(64),
  presence: "online",
  availability_mode: "unlocked_session",
  roots: [root],
};
const localStatus = {
  state: "online",
  device_id: "device_1",
  root_ids: ["root_1"],
  reason: null,
};

beforeEach(() => {
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText: vi.fn().mockResolvedValue(undefined) },
  });
  api.deviceLeases.mockResolvedValue({ leases: [] });
  api.devices.mockResolvedValue({ devices: [device] });
  api.revokeDevice.mockResolvedValue({ status: "ok" });
  api.revokeDeviceRoot.mockResolvedValue({ status: "ok" });
  native.hasDesktopRuntime.mockReturnValue(true);
  native.desktopDeviceStatus.mockResolvedValue(localStatus);
  native.listenDesktopDeviceStatus.mockResolvedValue(vi.fn());
  native.listenDeviceLeaseTerminals.mockImplementation(async (handler) => {
    native.leaseHandler = handler;
    return vi.fn();
  });
  native.bindDesktopRoot.mockResolvedValue(root);
  native.clearDesktopSession.mockResolvedValue(undefined);
  native.unbindDesktopRoot.mockResolvedValue(undefined);
  native.materializeArtifact.mockResolvedValue({
    status: "saved",
    handle: "materialized-handle",
  });
  native.takeDesktopReadResult.mockResolvedValue(new Uint8Array([65, 66, 67]));
  vi.spyOn(crypto, "randomUUID").mockReturnValue("11111111-1111-4111-8111-111111111111");
});

afterEach(() => {
  clearLocalDeviceActionSession();
  cleanup();
  vi.restoreAllMocks();
  vi.clearAllMocks();
  native.leaseHandler = null;
});

describe("Worker desktop device lifecycle", () => {
  it("consumes the desktop enrollment with the exact verifier bootstrap", async () => {
    api.startDeviceEnrollment.mockResolvedValue(enrollment);
    native.completeDesktopEnrollment.mockResolvedValue({
      device_id: "device_1",
      label: "Office Mac",
      public_key_fingerprint: "f".repeat(64),
      session_expires_at: "2030-01-02T00:00:00Z",
      lease_verifier_key_id: verifier.key_id,
    });
    render(<DeviceSettings />);
    fireEvent.change(screen.getByLabelText("Device label"), {
      target: { value: "Office Mac" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Enroll this desktop" }));
    await waitFor(() => expect(native.completeDesktopEnrollment).toHaveBeenCalledWith(enrollment));
    expect(await screen.findByText(/session and verifier are held in the OS keychain/i)).toBeTruthy();
    expect(screen.queryByText("one-time-code")).toBeNull();
  });

  it("rolls the server root back when native folder binding is cancelled", async () => {
    const created = { ...root, id: "root_new", label: "New workspace" };
    api.createDeviceRoot.mockResolvedValue({ root: created });
    native.bindDesktopRoot.mockResolvedValue(null);
    render(<DeviceSettings />);
    await waitFor(() => expect(api.devices).toHaveBeenCalled());
    fireEvent.change(screen.getByLabelText("Opaque root label"), {
      target: { value: "New workspace" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Register and choose local folder…" }));
    await waitFor(() => expect(native.bindDesktopRoot).toHaveBeenCalledWith(
      "root_new",
      "read_write",
      true,
    ));
    expect(api.revokeDeviceRoot).toHaveBeenCalledWith("device_1", "root_new");
    expect(await screen.findByText(/server root was rolled back/i)).toBeTruthy();
  });

  it("removes native root and enrollment state after authoritative revocation", async () => {
    render(<DeviceSettings />);
    await waitFor(() => expect(api.devices).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "Revoke" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm revoke" }));
    await waitFor(() => expect(native.unbindDesktopRoot).toHaveBeenCalledWith("root_1"));
    expect(api.revokeDeviceRoot).toHaveBeenCalledWith("device_1", "root_1");

    fireEvent.click(screen.getByRole("button", { name: "Revoke device" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm revoke device" }));
    await waitFor(() => expect(native.clearDesktopSession).toHaveBeenCalled());
    expect(api.revokeDevice).toHaveBeenCalledWith("device_1");
  });

  it("removes an orphaned local root without issuing a second server mutation", async () => {
    native.desktopDeviceStatus.mockResolvedValue({
      ...localStatus,
      root_ids: ["root_1", "root_orphan"],
    });
    render(<DeviceSettings />);

    const remove = await screen.findByRole("button", {
      name: "Remove local binding",
    });
    fireEvent.click(remove);
    expect(native.unbindDesktopRoot).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", {
      name: "Confirm local removal",
    }));

    await waitFor(() => expect(native.unbindDesktopRoot)
      .toHaveBeenCalledWith("root_orphan"));
    expect(api.revokeDeviceRoot).not.toHaveBeenCalled();
    expect(await screen.findByText(/No server root was changed/i)).toBeTruthy();
  });

  it("offers confirmed local cleanup for an unreadable enrollment", async () => {
    native.desktopDeviceStatus.mockResolvedValue({
      state: "reenrollment_required",
      device_id: null,
      root_ids: [],
      reason: "os_keychain_read_failed",
    });
    render(<DeviceSettings />);

    expect(await screen.findByText(/Browser sign-in remains independent/i))
      .toBeTruthy();
    fireEvent.click(screen.getByRole("button", {
      name: "Remove orphaned local enrollment",
    }));
    expect(native.clearDesktopSession).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", {
      name: "Confirm local enrollment removal",
    }));

    await waitFor(() => expect(native.clearDesktopSession).toHaveBeenCalled());
    expect(api.revokeDevice).not.toHaveBeenCalled();
    expect(await screen.findByText(/No server device was revoked/i)).toBeTruthy();
  });

  it("keeps browser and remote-device local controls honestly disabled", async () => {
    native.hasDesktopRuntime.mockReturnValue(false);
    render(<DeviceSettings />);
    await waitFor(() => expect(api.devices).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: "Create desktop handoff code" })).toBeTruthy();
    expect((screen.getByLabelText("Opaque root label") as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Request exact-action lease" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/browser cannot execute them/i)).toBeTruthy();
    expect(native.desktopDeviceStatus).not.toHaveBeenCalled();
    expect(api.invoke).not.toHaveBeenCalled();
  });

  it("reports desktop enrollment bundle copy success and failure", async () => {
    native.hasDesktopRuntime.mockReturnValue(false);
    api.startDeviceEnrollment.mockResolvedValue(enrollment);
    render(<DeviceSettings />);
    fireEvent.change(screen.getByLabelText("Device label"), {
      target: { value: "Office Mac" },
    });
    fireEvent.click(screen.getByRole("button", {
      name: "Create desktop handoff code",
    }));
    expect(await screen.findByText("one-time-code")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Copy desktop bundle" }));
    expect(await screen.findByText(/Desktop enrollment bundle copied/)).toBeTruthy();
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.stringContaining('"authorization_code":"one-time-code"'),
    );

    vi.mocked(navigator.clipboard.writeText).mockRejectedValueOnce(
      new Error("clipboard denied"),
    );
    fireEvent.click(screen.getByRole("button", { name: "Copy desktop bundle" }));
    expect(await screen.findByText(/enrollment bundle could not be copied/i))
      .toBeTruthy();
  });

  it("keeps a server-enrolled remote device view-only in the desktop app", async () => {
    native.desktopDeviceStatus.mockResolvedValue({
      state: "online",
      device_id: "different_device",
      root_ids: ["different_root"],
      reason: null,
    });
    render(<DeviceSettings />);
    expect(await screen.findByText(/not the device enrolled in the local native agent/i)).toBeTruthy();
    expect((screen.getByLabelText("Opaque root label") as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Request exact-action lease" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("remote · view only")).toBeTruthy();
    expect(api.invoke).not.toHaveBeenCalled();
  });
});

describe("Worker local-device dispatcher actions", () => {
  it("retains an exact pending retry across a React remount without browser storage", async () => {
    api.invoke.mockResolvedValue({
      status: "pending_human",
      hitl_request_id: "approval_remount",
    });
    const first = render(<DeviceSettings />);
    await waitFor(() => expect(api.devices).toHaveBeenCalled());
    fireEvent.change(screen.getByLabelText("Root-relative path"), {
      target: { value: "reports/remount.txt" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Request exact-action lease" }));
    expect(await screen.findByText(/approval_remount needs an independent approval/i)).toBeTruthy();
    expect(screen.getByText(/full reload clears it/i)).toBeTruthy();
    const exactRequest = api.invoke.mock.calls[0][0];

    first.unmount();
    render(<DeviceSettings />);
    const retry = await screen.findByRole("button", { name: "Retry approved action" });
    fireEvent.click(retry);
    await waitFor(() => expect(api.invoke).toHaveBeenCalledTimes(2));
    expect(api.invoke.mock.calls[1][0]).toEqual({
      ...exactRequest,
      approval_id: "approval_remount",
    });
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });

  it("reconciles a missed durable terminal receipt and available local read bytes after remount", async () => {
    api.invoke.mockResolvedValue({
      status: "ok",
      output: {
        status: "leased",
        lease_id: "lease_recovered",
        device_id: "device_1",
        root_id: "root_1",
        verb: "device.file.read",
        expires_at: "2030-01-01T00:01:00Z",
      },
    });
    const first = render(<DeviceSettings />);
    await waitFor(() => expect(api.devices).toHaveBeenCalled());
    fireEvent.change(screen.getByLabelText("Root-relative path"), {
      target: { value: "reports/recovered.txt" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Request exact-action lease" }));
    await waitFor(() => expect(api.invoke).toHaveBeenCalled());
    first.unmount();

    api.deviceLeases.mockResolvedValue({
      leases: [{
        id: "lease_recovered",
        device_id: "device_1",
        root_id: "root_1",
        verb: "device.file.read",
        status: "completed",
        issued_at: "2030-01-01T00:00:00Z",
        expires_at: "2030-01-01T00:01:00Z",
        settled_at: "2030-01-01T00:00:10Z",
        receipt: {
          byte_size: 3,
          content_digest: "b".repeat(64),
          reported_local_result_available: true,
        },
      }],
    });
    render(<DeviceSettings />);
    expect(await screen.findByText(/lease_recovered · Read · completed/i)).toBeTruthy();
    expect(await screen.findByRole("button", { name: "Save local read…" })).toBeTruthy();
    expect(screen.getByText(/Save before reloading/i)).toBeTruthy();
    expect(native.takeDesktopReadResult).toHaveBeenCalledWith("lease_recovered");
  });

  it("retries an unchanged approved read, receives local bytes, and offers native save", async () => {
    api.invoke
      .mockResolvedValueOnce({ status: "pending_human", hitl_request_id: "approval_1" })
      .mockResolvedValueOnce({
        status: "ok",
        output: {
          status: "leased",
          lease_id: "lease_1",
          device_id: "device_1",
          root_id: "root_1",
          verb: "device.file.read",
          expires_at: "2030-01-01T00:01:00Z",
        },
      });
    render(<DeviceSettings />);
    await waitFor(() => expect(native.listenDeviceLeaseTerminals).toHaveBeenCalled());
    fireEvent.change(screen.getByLabelText("Root-relative path"), {
      target: { value: "reports/final.txt" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Request exact-action lease" }));
    expect(await screen.findByText(/needs an independent approval in the originating chat/i)).toBeTruthy();
    const first = api.invoke.mock.calls[0][0];
    fireEvent.click(screen.getByRole("button", { name: "Retry approved action" }));
    await waitFor(() => expect(api.invoke).toHaveBeenCalledTimes(2));
    expect(api.invoke.mock.calls[1][0]).toEqual({
      ...first,
      approval_id: "approval_1",
    });
    await act(async () => {
      native.leaseHandler?.({
        lease_id: "lease_1",
        root_id: "root_1",
        verb: "device.file.read",
        status: "completed",
        receipt: {
          byte_size: 3,
          content_digest: "b".repeat(64),
          local_result_available: true,
        },
      });
    });
    const save = await screen.findByRole("button", { name: "Save local read…" });
    fireEvent.click(save);
    await waitFor(() => expect(native.materializeArtifact).toHaveBeenCalledWith(
      "final.txt",
      new Uint8Array([65, 66, 67]),
    ));
  });

  it("stages exact write bytes before invoking the ordinary device verb", async () => {
    native.stageDesktopWrite.mockResolvedValue({
      content_digest: "c".repeat(64),
      byte_size: 7,
    });
    api.invoke.mockResolvedValue({
      status: "ok",
      output: {
        status: "leased",
        lease_id: "lease_write",
        device_id: "device_1",
        root_id: "root_1",
        verb: "device.file.write",
        expires_at: "2030-01-01T00:01:00Z",
      },
    });
    render(<DeviceSettings />);
    await waitFor(() => expect(api.devices).toHaveBeenCalled());
    fireEvent.change(screen.getByLabelText("Local action"), {
      target: { value: "device.file.write" },
    });
    fireEvent.change(screen.getByLabelText("Root-relative destination"), {
      target: { value: "reports/result.txt" },
    });
    const file = new File(["payload"], "payload.txt", { type: "text/plain" });
    fireEvent.change(screen.getByLabelText("Local payload"), {
      target: { files: [file] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Request exact-action lease" }));
    await waitFor(() => expect(api.invoke).toHaveBeenCalled());
    expect(native.stageDesktopWrite.mock.invocationCallOrder[0])
      .toBeLessThan(api.invoke.mock.invocationCallOrder[0]);
    expect(api.invoke).toHaveBeenCalledWith({
      noun: "device",
      verb: "device.file.write",
      params: {
        device_id: "device_1",
        root_id: "root_1",
        relative_path: "reports/result.txt",
        content_digest: "c".repeat(64),
        byte_size: 7,
        overwrite: false,
      },
      idempotency_key: "11111111-1111-4111-8111-111111111111",
    });
  });

  it("submits commands as argv data with no shell string field", async () => {
    api.invoke.mockResolvedValue({
      status: "ok",
      output: {
        status: "leased",
        lease_id: "lease_command",
        device_id: "device_1",
        root_id: "root_1",
        verb: "device.command.run",
        expires_at: "2030-01-01T00:01:00Z",
      },
    });
    render(<DeviceSettings />);
    await waitFor(() => expect(api.devices).toHaveBeenCalled());
    fireEvent.change(screen.getByLabelText("Local action"), {
      target: { value: "device.command.run" },
    });
    fireEvent.change(screen.getByLabelText("Command argv"), {
      target: { value: '[\"git\", \"status\", \"--short\"]' },
    });
    fireEvent.click(screen.getByRole("button", { name: "Request exact-action lease" }));
    await waitFor(() => expect(api.invoke).toHaveBeenCalledWith(expect.objectContaining({
      noun: "device",
      verb: "device.command.run",
      params: {
        device_id: "device_1",
        root_id: "root_1",
        argv: ["git", "status", "--short"],
        cwd_relative: null,
        timeout_seconds: 30,
      },
    })));
    expect(JSON.stringify(api.invoke.mock.calls[0][0])).not.toContain("shell");
  });
});
