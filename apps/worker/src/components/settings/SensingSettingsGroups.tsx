import type {
  SensingCapabilityDecision,
  SensingResponse,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";
import {
  SettingsButton,
  SettingsGroup,
  SettingsRow,
  SettingsSelect,
  SettingsToggle,
} from "./rowKit";

export interface CameraChoice {
  camera_id: string;
  label: string;
}

export type SensingSave = (
  apply: () => Promise<SensingResponse>,
  optimistic: SensingResponse | null,
  failure: string,
) => Promise<void>;

const RETENTION_OPTIONS: Array<{ label: string; hours: number }> = [
  { label: "6 hours", hours: 6 },
  { label: "24 hours", hours: 24 },
  { label: "3 days", hours: 72 },
  { label: "7 days", hours: 168 },
];
const HOURS = Array.from({ length: 24 }, (_, hour) => `${String(hour).padStart(2, "0")}:00`);
const NO_CAMERA = "No camera chosen";
const PRESENCE_BLOCKER_COPY: Record<string, string> = {
  presence_not_enrolled:
    "No face has been enrolled on this computer, so there is nothing to recognise.",
  presence_not_calibrated:
    "The enrolled face has no room-calibrated threshold. Presence will not guess one.",
};

function hourLabel(hour: number): string {
  return HOURS[Math.min(Math.max(hour, 0), 23)];
}

function retentionLabel(hours: number): string {
  return RETENTION_OPTIONS.find((option) => option.hours === hours)?.label ?? `${hours} hours`;
}

function capabilityName(capability: string): string {
  return capability === "presence" ? "Presence" : "Camera observations";
}

function CameraToggleRow({ busy, save, sensing }: {
  busy: boolean;
  save: SensingSave;
  sensing: SensingResponse;
}) {
  const { camera } = sensing;
  return (
    <SettingsRow
      control={<SettingsToggle disabled={busy} label="Camera" on={camera.enabled} onToggle={(next) => void save(
        () => client.putSensingCamera({ enabled: next }),
        { ...sensing, camera: { ...camera, enabled: next } },
        "The camera setting could not be saved.",
      )} />}
      desc={camera.source === "safe_default" && !camera.enabled
        ? "Off because nobody has turned it on. Nothing is being watched."
        : "When this is off, no frame is captured and no character can ask for one."}
      tech="sensing.camera.enabled"
      title="Camera"
    />
  );
}

function CameraChoiceRow({ binding, busy, cameras, deviceId, enabled, onChoose }: {
  binding: SensingResponse["camera"]["binding"];
  busy: boolean;
  cameras: CameraChoice[];
  deviceId: string | null;
  enabled: boolean;
  onChoose(choice: CameraChoice | null): void;
}) {
  const chosen = binding ? cameras.find((camera) => camera.camera_id === binding.camera_id) : undefined;
  const options = [NO_CAMERA, ...cameras.map((camera) => camera.label)];
  const value = chosen?.label ?? (binding ? binding.label || binding.camera_id : NO_CAMERA);
  const choosable = cameras.length > 0 && deviceId !== null;
  return (
    <SettingsRow
      control={<SettingsSelect
        disabled={busy || !enabled || !choosable}
        label="Which camera"
        onChange={(label) => onChoose(cameras.find((camera) => camera.label === label) ?? null)}
        options={options.includes(value) ? options : [...options, value]}
        value={value}
      />}
      desc={choosable
        ? "One of the cameras this computer published. Nothing else can be selected."
        : "This computer has published no camera to choose from."}
      tech="sensing.camera.binding"
      title="Which camera"
    />
  );
}

function RetentionRow({ busy, save, sensing }: {
  busy: boolean;
  save: SensingSave;
  sensing: SensingResponse;
}) {
  const { camera } = sensing;
  return (
    <SettingsRow
      control={<SettingsSelect
        disabled={busy}
        label="Keep what it saw"
        onChange={(label) => {
          const hours = RETENTION_OPTIONS.find((option) => option.label === label)?.hours;
          if (hours === undefined) return;
          void save(
            () => client.putSensingCamera({ retention_hours: hours }),
            { ...sensing, camera: { ...camera, retention_hours: hours } },
            "The retention window could not be saved.",
          );
        }}
        options={RETENTION_OPTIONS.map((option) => option.label)}
        value={retentionLabel(camera.retention_hours)}
      />}
      desc="Frames and the observations describing them are deleted together, so a record never outlives its image."
      tech="sensing.camera.retention_hours"
      title="Keep what it saw"
    />
  );
}

function QuietHoursRow({ busy, save, sensing }: {
  busy: boolean;
  save: SensingSave;
  sensing: SensingResponse;
}) {
  const { camera } = sensing;
  const change = (edge: "start" | "end", label: string) => {
    const hour = HOURS.indexOf(label);
    const quiet_hours = { ...camera.quiet_hours, [edge]: hour };
    void save(
      () => client.putSensingCamera({ quiet_hours }),
      null,
      "Quiet hours could not be saved.",
    );
  };
  return (
    <SettingsRow
      control={<div className="settings-status">
        <SettingsSelect disabled={busy} label="Quiet hours start" onChange={(label) => change("start", label)} options={HOURS} value={hourLabel(camera.quiet_hours.start)} />
        <SettingsSelect disabled={busy} label="Quiet hours end" onChange={(label) => change("end", label)} options={HOURS} value={hourLabel(camera.quiet_hours.end)} />
      </div>}
      desc="Between these times nothing is captured, whatever a character asks for."
      tech="sensing.camera.quiet_hours"
      title="Quiet hours"
    />
  );
}

export function CameraSettingsGroup({ busy, cameras, deviceId, save, sensing }: {
  busy: boolean;
  cameras: CameraChoice[];
  deviceId: string | null;
  save: SensingSave;
  sensing: SensingResponse;
}) {
  return (
    <SettingsGroup
      foot="Boltrig controls the camera connection for this computer. A character may request access, but never owns the camera and is told when access is off."
      title="What this computer may see"
    >
      <CameraToggleRow busy={busy} save={save} sensing={sensing} />
      <CameraChoiceRow
        binding={sensing.camera.binding}
        busy={busy}
        cameras={cameras}
        deviceId={deviceId}
        enabled={sensing.camera.enabled}
        onChoose={(choice) => void save(
          () => client.putSensingCamera({
            camera_id: choice?.camera_id ?? null,
            ...(choice && deviceId ? { device_id: deviceId } : {}),
          }),
          null,
          "The camera choice could not be saved.",
        )}
      />
      <RetentionRow busy={busy} save={save} sensing={sensing} />
      <QuietHoursRow busy={busy} save={save} sensing={sensing} />
    </SettingsGroup>
  );
}

export function PresenceSettingsGroup({ busy, save, sensing }: {
  busy: boolean;
  save: SensingSave;
  sensing: SensingResponse;
}) {
  const { enrollment, presence } = sensing;
  const blocker = presence.blocked_by ?? null;
  return (
    <SettingsGroup title="Who is in the room">
      <SettingsRow
        control={<SettingsToggle disabled={busy || blocker !== null} label="Presence" on={presence.enabled} onToggle={(next) => void save(
          () => client.putSensingPresence({ enabled: next }),
          { ...sensing, presence: { ...presence, enabled: next } },
          "The presence setting could not be saved.",
        )} />}
        desc={blocker
          ? PRESENCE_BLOCKER_COPY[blocker] ?? "Presence is not available."
          : "Whether it is you in front of the camera. One answer for every character."}
        tech="sensing.presence.enabled"
        title="Presence"
      />
      <SettingsRow
        control={<SettingsButton
          disabled={busy || !enrollment.present}
          label="Forget"
          onClick={() => void save(
            () => client.deleteSensingEnrollment(),
            null,
            "The enrolled face could not be forgotten.",
          )}
          title="Forget the enrolled face and turn presence off"
          tone="danger"
        />}
        desc={enrollment.present
          ? `${enrollment.count} samples, recognised at ${enrollment.threshold ?? "—"}. ${enrollment.far_measured ? "The false-accept rate has been measured." : "The false-accept rate has NOT been measured, so this is not an identity check."}`
          : "No face has been enrolled on this computer."}
        tech="sensing.enrollment"
        title="The enrolled face"
      />
      <SettingsRow
        desc="Anchor images are the character's face and travel with it. The enrolled face is yours, and Boltrig keeps it here."
        title="It is never included in a character bundle"
      />
    </SettingsGroup>
  );
}

function CapabilityRow({ decision }: { decision: SensingCapabilityDecision }) {
  const granted = decision.status === "granted";
  return (
    <SettingsRow
      control={<span className="settings-value">{granted ? "Available" : "Refused"}</span>}
      desc={granted
        ? "A character that asks for this is given it."
        : decision.detail ?? "This capability is not available."}
      tech={decision.reason}
      title={capabilityName(decision.capability)}
    />
  );
}

export function CapabilitySettingsGroup({ decisions }: {
  decisions: SensingCapabilityDecision[];
}) {
  return (
    <SettingsGroup
      foot="Checked each time it is asked, never remembered — moving a switch above changes these on the next request."
      title="What a character is told"
    >
      {decisions.map((decision) => <CapabilityRow decision={decision} key={decision.capability} />)}
    </SettingsGroup>
  );
}
