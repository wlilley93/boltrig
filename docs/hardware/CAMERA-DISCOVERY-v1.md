# Boltrig Camera Discovery v1

EMEET Pixy is fixture #1, not a product-specific integration. The discovery
layer is standards-first and turns bounded native probe evidence into a local
capability map. It never sends HID reports, runs profile commands, or treats a
matching VID/PID as proof of physical behavior.

## Discovery stages

1. Presence and interface inventory: label, UVC/UAC/HID and other interface
   classes; no capture or movement.
2. Read-only capability inspection: video formats, UVC descriptor/control
   reads, UAC formats, and HID descriptor metadata.
3. Explicit local snapshot verification: one bounded frame, decode check, then
   discard.
4. Explicit actuator verification: one smallest safe movement per axis,
   readback, exact restoration, and failure-safe reporting.
5. Explicit trusted-profile verification only when standard protocols cannot
   expose the requested feature. Unknown HID remains inert.

The public model uses explicit states: `unsupported`, `advertised`, `readable`,
`proven`, `unknown`, `invalid_descriptor`, `permission_required`,
`device_busy`, and `unavailable`. Every capability also carries internal
evidence. The agent-facing projection exposes PTZ mutation only when both axes
are proven; descriptors alone never create a mutating verb.

## Current v1 foundation

- `boltrig/camera/discovery.py` converts native probe JSON into the versioned
  semantic map and dynamic verb projection.
- `boltrig/camera/backend.py` defines the manufacturer-neutral backend and
  explicit operation outcomes.
- `boltrig/camera/profiles.py` loads local TOML metadata only; executable
  profile fields are rejected and trust is explicit.
- `boltrig/camera/cache.py` stores opaque local bindings and capability
  summaries atomically. Raw serials, registry paths, frames, and probe payloads
  are not persisted.
- `boltrig/adapters/builtin/camera.py` defines the opt-in read-only adapter
  surface: `camera.device.list`, `camera.device.status`,
  `camera.device.capabilities`, and `camera.snapshot`.
- `camera-profiles/emeet-pixy/profile.toml` records Pixy's fixed-width PTZ
  quirk and invalid privacy descriptor. It does not contain HID commands.
- `tests/fixtures/cameras/emeet-pixy-00c0/probe.json` is a redacted golden
  fixture built from the measured report.
- `apps/worker/src-tauri/src/camera_discovery.rs`, `camera_discovery.m`, and
  `camera_uvc.m` provide macOS AVFoundation inventory, opaque local IDs,
  permission state, bounded format counts, periodic hotplug change events,
  standard UVC Camera Terminal reads, bounded one-frame capture, and guarded
  PTZ get/set/readback/restoration. The UVC bridge re-identifies the exact
  descriptor fingerprint before every control operation and closes all native
  handles. Native keys never leave the projection.
- `apps/worker/src/components/CameraDiscoverySettings.tsx` exposes the local
  evidence/status view and explicit verification actions in Advanced settings.
- `boltrig/models/camera_actions.py`, `boltrig/camera_leases.py`, and
  `apps/worker/src-tauri/src/camera_protocol.rs` define separate signed PTZ
  lease grammars. They contain no root, path, argv, HID, or shell fields and
  bind every action to the camera descriptor fingerprint.
- `boltrig/store/camera_memory.py`, `camera_pg.py`, and migration
  `0068_camera_uvc_leases.py` persist camera bindings and root-free leases.
  The authenticated Worker transport publishes bounded observations, then
  claims and settles only signed `camera.ptz.get` / `camera.ptz.set` leases.
  Native execution never calls the filesystem/argv executor.

The native bridge remains fail-closed for privacy and proprietary HID. Snapshot
proof is a bounded local one-frame capture whose digest is reported without
retaining the frame. PTZ proof requires a guarded one-step pan and tilt, native
readback, visual frame change, and exact restoration; descriptors alone only
produce readable/writable states. Server-side PTZ leases additionally require a
published `proven` binding and exact human approval.

## Pixy projection

The golden fixture produces:

- UVC video and UAC audio enumeration;
- snapshot `proven` after one-frame evidence;
- pan and tilt `proven` with UVC limits, step, readback, physical-verification,
  and restoration evidence;
- zoom and focus `readable`, not proven for mutation;
- tracking `unknown` because HID is descriptor-only;
- privacy `invalid_descriptor` because the boolean controls return `0x03`;
- no network/storage/serial capability is opened automatically.

The generic runtime sees UVC PTZ. It does not need an EMEET PTZ driver. Privacy
is read-only descriptor evidence; no privacy write is exposed or attempted.
