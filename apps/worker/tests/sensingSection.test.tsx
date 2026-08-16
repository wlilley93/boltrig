// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  sensing: vi.fn(),
  putSensingCamera: vi.fn(),
  putSensingPresence: vi.fn(),
  deleteSensingEnrollment: vi.fn(),
}));

const desktop = vi.hoisted(() => ({
  desktopDeviceStatus: vi.fn(),
  desktopCameraStatus: vi.fn(),
  listenDesktopCameraDiscovery: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));
vi.mock("../src/desktop", () => ({ desktopDeviceStatus: desktop.desktopDeviceStatus }));
vi.mock("../src/desktopCamera", () => ({
  desktopCameraStatus: desktop.desktopCameraStatus,
  listenDesktopCameraDiscovery: desktop.listenDesktopCameraDiscovery,
}));

import { SensingSection } from "../src/components/settings/SensingSection";
import { SETTINGS_SECTIONS, isSettingsSection } from "../src/settingsSections";

const CAMERA_OFF = {
  status: "ok" as const,
  camera: {
    enabled: false,
    source: "safe_default" as const,
    binding: null,
    retention_hours: 24,
    quiet_hours: { start: 22, end: 8 },
  },
  presence: {
    enabled: false,
    source: "safe_default" as const,
    blocked_by: "presence_not_enrolled" as const,
  },
  enrollment: {
    present: false,
    count: 0,
    threshold: null,
    far_measured: false,
    exportable: false as const,
  },
  capabilities: [
    {
      status: "refused" as const,
      capability: "camera_observations",
      reason: "camera_disabled" as const,
      detail: "The camera is turned off in Settings › Camera and presence.",
      remedy: "settings:sensing" as const,
    },
    {
      status: "refused" as const,
      capability: "presence",
      reason: "camera_disabled" as const,
      detail: "The camera is turned off in Settings › Camera and presence.",
      remedy: "settings:sensing" as const,
    },
  ],
};

const CAMERA_ON = {
  ...CAMERA_OFF,
  camera: {
    ...CAMERA_OFF.camera,
    enabled: true,
    source: "user_override" as const,
    binding: { camera_id: `camera_${"a".repeat(32)}`, device_id: "dev-1", label: "Studio cam" },
  },
  presence: { enabled: false, source: "safe_default" as const, blocked_by: null },
  enrollment: {
    present: true,
    count: 150,
    threshold: 0.62,
    far_measured: false,
    exportable: false as const,
  },
  capabilities: [
    { status: "granted" as const, capability: "camera_observations" },
    {
      status: "refused" as const,
      capability: "presence",
      reason: "presence_disabled" as const,
      detail: "Presence is turned off in Settings › Camera and presence.",
      remedy: "settings:sensing" as const,
    },
  ],
};

beforeEach(() => {
  api.sensing.mockResolvedValue(CAMERA_OFF);
  api.putSensingCamera.mockResolvedValue(CAMERA_ON);
  api.putSensingPresence.mockResolvedValue(CAMERA_ON);
  api.deleteSensingEnrollment.mockResolvedValue(CAMERA_OFF);
  // Nothing published: the browser case, and the honest default for these tests.
  desktop.desktopDeviceStatus.mockResolvedValue(null);
  desktop.desktopCameraStatus.mockResolvedValue(null);
  desktop.listenDesktopCameraDiscovery.mockResolvedValue(() => undefined);
});

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

describe("camera and presence settings", () => {
  it("keeps old sensing links valid inside the top-level Behaviour section", () => {
    expect(isSettingsSection("sensing")).toBe(true);
    const entry = SETTINGS_SECTIONS.find((section) => section.id === "behaviour");
    expect(entry?.label).toBe("Behaviour");
    expect(SETTINGS_SECTIONS.findIndex((section) => section.id === "behaviour")).toBe(1);
    expect(SETTINGS_SECTIONS.some((section) => section.id === "sensing")).toBe(false);
  });

  it("shows the camera off by safe default and turns it on through the kernel", async () => {
    render(<SensingSection />);

    const toggle = await screen.findByRole("switch", { name: "Camera" });
    expect(toggle.getAttribute("aria-checked")).toBe("false");
    expect(screen.getByText(/Off because nobody has turned it on/)).toBeTruthy();

    fireEvent.click(toggle);
    await waitFor(() => {
      expect(api.putSensingCamera).toHaveBeenCalledWith({ enabled: true });
    });
    await waitFor(() => {
      expect(screen.getByRole("switch", { name: "Camera" }).getAttribute("aria-checked"))
        .toBe("true");
    });
  });

  it("keeps the compact Sight and Presence views plain, with details behind info controls", async () => {
    api.sensing.mockResolvedValue(CAMERA_ON);
    const view = render(<SensingSection head={false} view="sight" />);

    expect(await screen.findByRole("button", { name: "About sight" })).toBeTruthy();
    expect(screen.getByRole("tooltip").textContent).toContain("captures no camera frame");
    expect(screen.queryByText(/record never outlives its image/)).toBeNull();

    view.rerender(<SensingSection head={false} view="presence" />);
    expect(await screen.findByRole("button", { name: "About presence" })).toBeTruthy();
    expect(screen.getByRole("tooltip").textContent).toContain("not an identity check");
    expect(screen.queryByText("It is never included in a character bundle")).toBeNull();
  });

  it("draws the honest refusal a character gets, with its reason", async () => {
    render(<SensingSection />);

    await screen.findByRole("switch", { name: "Camera" });
    expect(screen.getByText("Camera observations")).toBeTruthy();
    expect(screen.getAllByText("Refused").length).toBe(2);
    expect(
      screen.getAllByText("The camera is turned off in Settings › Camera and presence.").length,
    ).toBeGreaterThan(0);
  });

  it("refuses to offer presence when there is no enrolment to recognise against", async () => {
    render(<SensingSection />);

    const presence = await screen.findByRole("switch", { name: "Presence" });
    expect(presence.hasAttribute("disabled")).toBe(true);
    expect(screen.getByText(/No face has been enrolled on this computer, so there is nothing/))
      .toBeTruthy();
    fireEvent.click(presence);
    expect(api.putSensingPresence).not.toHaveBeenCalled();
  });

  it("states that the enrolled face never leaves in a bundle, and offers to forget it", async () => {
    api.sensing.mockResolvedValue(CAMERA_ON);
    render(<SensingSection />);

    expect(await screen.findByText("It is never included in a character bundle")).toBeTruthy();
    expect(screen.getByText(/The false-accept rate has NOT been measured/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Forget" }));
    await waitFor(() => expect(api.deleteSensingEnrollment).toHaveBeenCalled());
  });

  it("saves the retention window the user chose", async () => {
    api.sensing.mockResolvedValue(CAMERA_ON);
    render(<SensingSection />);

    const select = await screen.findByLabelText("Keep what it saw");
    fireEvent.change(select, { target: { value: "3 days" } });
    await waitFor(() => {
      expect(api.putSensingCamera).toHaveBeenCalledWith({ retention_hours: 72 });
    });
  });

  it("reverts and says so when the kernel refuses the change", async () => {
    api.putSensingCamera.mockResolvedValue({
      ...CAMERA_OFF,
      status: "error",
      reason: "camera_binding_unavailable",
    });
    render(<SensingSection />);

    fireEvent.click(await screen.findByRole("switch", { name: "Camera" }));
    expect((await screen.findByRole("alert")).textContent)
      .toContain("camera_binding_unavailable");
    expect(screen.getByRole("switch", { name: "Camera" }).getAttribute("aria-checked"))
      .toBe("false");
  });

  it("offers nothing to pick when this computer has published no camera", async () => {
    api.sensing.mockResolvedValue(CAMERA_ON);
    render(<SensingSection />);

    const picker = await screen.findByLabelText("Which camera");
    expect(picker.hasAttribute("disabled")).toBe(true);
    expect(screen.getByText("This computer has published no camera to choose from."))
      .toBeTruthy();
  });

  it("picks only from the cameras this computer published, and binds to its device", async () => {
    api.sensing.mockResolvedValue({ ...CAMERA_ON, camera: { ...CAMERA_ON.camera, binding: null } });
    desktop.desktopDeviceStatus.mockResolvedValue({ device_id: "dev-1", root_ids: [], reason: null, state: "online" });
    desktop.desktopCameraStatus.mockResolvedValue({
      schema_version: 1,
      state: "ready",
      runtime: "uvc",
      refreshed_at: "2026-08-13T00:00:00Z",
      reason: null,
      cameras: [{ camera_id: `camera_${"a".repeat(32)}`, label: "Studio cam", product: "cam" }],
    });
    render(<SensingSection />);

    const picker = await screen.findByLabelText("Which camera");
    await waitFor(() => expect(picker.hasAttribute("disabled")).toBe(false));
    fireEvent.change(picker, { target: { value: "Studio cam" } });

    await waitFor(() => {
      expect(api.putSensingCamera).toHaveBeenCalledWith({
        camera_id: `camera_${"a".repeat(32)}`,
        device_id: "dev-1",
      });
    });
  });

  it("says so rather than crashing when a kernel has no sensing surface", async () => {
    api.sensing.mockRejectedValue(new Error("unavailable"));
    render(<SensingSection />);

    expect(await screen.findByText(/could not be read, so nothing here has been changed/))
      .toBeTruthy();
    expect(screen.queryByRole("switch", { name: "Camera" })).toBeNull();
  });
});
