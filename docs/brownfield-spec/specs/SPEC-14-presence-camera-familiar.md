---
area: 14 Presence, devices, camera, emotion and the Familiar
id-block: BT-REQ-1400 to BT-REQ-1499
referent commit: 19bcae7fa81663fe8998377c86451ba08fb16e48 (origin/main)
author-agent: brownfield-spec author, area 14
date: 2026-08-24
---

# SPEC 14: Presence, devices, camera, emotion and the Familiar

## Bound of this reading

Every file named in the area scope was opened in full: `boltrig/camera_leases.py`,
`boltrig/device_leases.py`, `boltrig/camera/*.py` (7 modules, 1165 lines),
`boltrig/emotion/*.py` (4 modules, 986 lines), `boltrig/addons/*.py`,
`boltrig/branding.py`, `boltrig/kernel/camera_agent_routes.py`,
`device_agent_routes.py`, `device_actions.py`, `device_route_support.py`,
`device_crypto.py`, `device_routes.py`, `familiar_phenotype_routes.py`,
`sensing_policy.py`, `sensing_capability.py`, `sensing_routes.py`,
`hands_registry.py`, `desktop_routes.py`, the eight decision records, and
`camera-profiles/`.

Sampled rather than read line by line, with the sampling rule stated:

- `familiar/` (13,866 lines): every file's top-level definitions plus depth on
  `main.c` (constants, the phenotype and express readers, the presence model),
  `genotype.h` in full, `README.md` in full, `Makefile` in full, `check.sh` head.
  The four GLSL bodies (`familiar.frag` 2,033 lines and the four 1,667-line realm
  variants) were NOT read as shaders. Claims here about the shader are claims
  about its uniform list and its byte identity, not about what it draws.
- `apps/worker/src/components/familiar/` and `canvas/familiar*`: every module's
  exported surface, depth on `FamiliarState.ts`, `FamiliarStage.tsx`,
  `useFamiliarRenderer.ts`, `FamiliarGenotype.ts`, `familiarTuning.ts`,
  `familiarPresets.ts` and the first 260 lines of `FamiliarWebGLRenderer.ts`.
  `familiarDrive.ts`, `familiarMood.ts`, `familiarUniforms.ts`, `FamiliarBadge.tsx`
  were read for their exports only.
- `apps/worker/src-tauri/src/` (9,576 lines): `camera_protocol.rs` in full,
  depth on `camera_discovery.rs` lease and identity paths and on `device_agent.rs`
  poll and camera-lease paths, targeted reads of `camera_uvc.m`. `local_agent.rs`
  (1,783 lines) read at the level of its constants and function signatures only.

Anything not covered by that bound is not asserted here.

---

## 2. Purpose

This subsystem is how Boltrig reaches, and is seen by, the physical world around
one person: a signed-lease plane that lets a cloud kernel act on an enrolled
desktop's files, shell and USB camera without ever holding a socket into that
machine; a consent surface that decides whether anything watches at all; and a
body, the Familiar, that renders the machine's measured mood without being able
to influence a single decision it makes. The three are deliberately severable and
meet only at named, versioned files and HTTP contracts. Every capability here
fails toward off, toward a resting expression, or toward a named refusal, never
toward silent action.

## 3. Boundaries

**What this area owns.** Device enrollment, device roots and device leases;
camera bindings and camera leases; the sensing consent settings and their
refusal vocabulary; the emotion engine, its data tables and its relay; the
`familiar.express` verb and its channel; the desktop-hands registry and its pull
surface; the addon registry and the product name derived from it; the desktop
familiar surface (`familiar/`) and the Worker Familiar Stage.

**What it must not touch, and the rule.**

- **Emotion may never influence dispatch.** The kernel's ONE emotion touch is the
  relay factory: [`boltrig/kernel/__init__.py:70`](../../../boltrig/kernel/__init__.py)
  `"from boltrig.emotion.relay import build_event_relay"` and
  [`boltrig/kernel/__init__.py:79`](../../../boltrig/kernel/__init__.py)
  `"self.events = build_emotion_relay(backend=event_relay)"`. No other module under
  `boltrig/kernel/` may import `boltrig.emotion`; the ban is AST-enforced by
  `tests/emotion/test_relay.py::test_no_kernel_module_imports_the_emotion_package`
  under invariant EMO-1 ([`tests/invariants.yaml:2188`](../../../tests/invariants.yaml)
  `"Emotion is strictly downstream of dispatch"`).
- **The Worker phenotype route may not import the emotion package either.** It
  reads the same published FILE:
  [`boltrig/kernel/familiar_phenotype_routes.py:3`](../../../boltrig/kernel/familiar_phenotype_routes.py)
  `"this module reads the same versioned phenotype"`, and it imports nothing from
  the emotion package: [`boltrig/kernel/familiar_phenotype_routes.py:5`](../../../boltrig/kernel/familiar_phenotype_routes.py)
  `"and this module imports nothing from"`, bound by EMO-7.
- **The desktop familiar surface imports nothing from boltrig (WL-1).** Its only
  coupling is `$XDG_RUNTIME_DIR/boltrig-phenotype.json`:
  [`familiar/README.md:60`](../../../familiar/README.md)
  `"this surface imports nothing from"`, statically checked by
  [`familiar/check.sh:12`](../../../familiar/check.sh)
  `"grep -nE '#include .*boltrig|-lboltrig"`.
- **Adapters may not import kernel transport.** `familiar.py` and `desktop.py`
  take only `boltrig.adapters.base` plus `boltrig.models` plus stdlib; the hands
  registry is injected: [`boltrig/adapters/builtin/desktop.py:19`](../../../boltrig/adapters/builtin/desktop.py)
  `"Severability mirrors familiar.py"`.
- **Camera leases must not reuse the device-root tables.** Stated at
  [`boltrig/camera_leases.py:4`](../../../boltrig/camera_leases.py)
  `"There is no filesystem root, argv, shell primitive, HID report"` and enforced
  in the Rust verifier's exact-key check
  ([`apps/worker/src-tauri/src/camera_protocol.rs:138`](../../../apps/worker/src-tauri/src/camera_protocol.rs)
  `"fn exact_keys"`).
- **A character bundle ships configuration, never executable code, and may never
  carry the enrolled face.** [`boltrig/kernel/sensing_policy.py:61`](../../../boltrig/kernel/sensing_policy.py)
  `"THE ENROLLED FACE IS KERNEL DATA, NEVER BUNDLE DATA."`
- **Camera profiles may not carry executable metadata.**
  [`boltrig/camera/profiles.py:31`](../../../boltrig/camera/profiles.py)
  `"_FORBIDDEN_KEYS = {"` with `command`, `download`, `executable`, `exec`,
  `module`, `script`, `url` refused at parse.

**The four unrelated meanings of "presence" in this area.** They are not one
concept and confusing them has already produced wrong prose in this repository:

| Sense | Where | What it is |
| --- | --- | --- |
| device presence | [`boltrig/models/devices.py:12`](../../../boltrig/models/devices.py) `"DEVICE_PRESENCE = ("offline", "online""` | a column on `devices`, four legal values |
| sensing presence | [`boltrig/kernel/sensing_policy.py:46`](../../../boltrig/kernel/sensing_policy.py) `"PRESENCE_ENABLED = "sensing.presence.enabled""` | face recognition consent, off by default |
| presence equals provisioning | [`docs/decisions/0035-presence-equals-provisioning.md:28`](../../../docs/decisions/0035-presence-equals-provisioning.md) `"Deployment shape is expressed by"` | a deployment doctrine: no shape flags |
| familiar presence | [`familiar/main.c:164`](../../../familiar/main.c) `"Presence: 1 = the desktop is bare"` and [`apps/worker/src/components/canvas/familiarTuning.ts:145`](../../../apps/worker/src/components/canvas/familiarTuning.ts) `"presence: number;"` | how large the body sits on screen |

## 4. Objects and contracts

### 4.1 Enrolled device plane

| Object | Fields | Lifecycle |
| --- | --- | --- |
| `DeviceEnrollment` | `id, tenant_id, owner_id, label, authorization_code_hash, expires_at, created_at, consumed_at` | created by a human, single use, 10 minute TTL |
| `EnrolledDevice` | `id, tenant_id, owner_id, label, public_key, public_key_fingerprint, lease_verify_key_id, availability_mode, presence, session_token_hash, session_expires_at, last_seen_at, revoked_at` | created on enrollment completion; `presence` goes `offline` then `online` then `revoked` |
| `DeviceRoot` | `id, tenant_id, device_id, label, scope, command_enabled, git_enabled, revoked_at` | registered by the owning human, per device |
| `DeviceLease` | `id, tenant_id, device_id, root_id, owner_id, verb, action, action_digest, approval_id, issued_at, expires_at, signature, signing_key_id, status, claim_token_hash, claim_expires_at, claimed_at, settled_at, receipt` | `issued` then `claimed` then `completed`/`failed`; `expired` is a projection, not a stored transition |

Definitions: [`boltrig/models/devices.py:24`](../../../boltrig/models/devices.py)
`"class DeviceEnrollment"` through
[`boltrig/models/devices.py:108`](../../../boltrig/models/devices.py)
`"return json.dumps("`.

Constants: `ENROLLMENT_TTL = 10 minutes`, `SESSION_TTL = 24 hours`,
`CLAIM_TTL = 5 minutes` at
[`boltrig/kernel/device_route_support.py:21`](../../../boltrig/kernel/device_route_support.py)
`"ENROLLMENT_TTL = timedelta(minutes=10)"`. Lease TTL is 120 seconds:
[`boltrig/device_leases.py:14`](../../../boltrig/device_leases.py)
`"DEVICE_LEASE_TTL = timedelta(seconds=120)"`.

Enum surfaces: `DEVICE_ROOT_SCOPES = ("read", "read_write")`,
`DEVICE_LEASE_STATUSES` five values, `DEVICE_LEASE_VERBS` four verbs
([`boltrig/models/devices.py:13`](../../../boltrig/models/devices.py)
`"DEVICE_ROOT_SCOPES = ("read", "read_write")"`).

**`availability_mode` has exactly one legal value.**
[`migrations/versions/0042_desktop_devices.py:40`](../../../migrations/versions/0042_desktop_devices.py)
`"CHECK (availability_mode IN ('unlocked_session'))"`. It is projected to the
owner ([`boltrig/kernel/device_route_support.py:64`](../../../boltrig/kernel/device_route_support.py)
`""availability_mode": device.availability_mode,"`) and to the Worker UI, where
it is printed as text.

### 4.2 Canonical device action

`canonical_device_action(device_id, root_id, verb, raw)` returns the exact action
object and its sha256 digest over
`{"noun": "device", "params": {...}, "verb": ..., "version": 1}`
([`boltrig/models/device_actions.py:56`](../../../boltrig/models/device_actions.py)
`"def _action_digest"`). Bounds:

| Constant | Value | Meaning |
| --- | --- | --- |
| `MAX_FILE_BYTES` | 104,857,600 | read/write cap |
| `MAX_PATH_BYTES` | 1024 | relative path bytes |
| `MAX_ARG_BYTES` | 4096 | one argv element |
| `MAX_ARGS` | 64 | argv length |
| `MAX_DIRECTORY_ENTRIES` | 100 | listing cap |

[`boltrig/models/device_actions.py:13`](../../../boltrig/models/device_actions.py)
`"MAX_FILE_BYTES = 100 * 1024 * 1024"`.

Paths are relative only, no leading `/`, no backslash, no NUL, no empty/`.`/`..`
segment ([`boltrig/models/device_actions.py:26`](../../../boltrig/models/device_actions.py)
`"if "\\\\" in value or "\\x00" in value or value.startswith("/")"`).
`device.command.run` takes `argv` only, plus an optional relative cwd and a
1..300 second timeout: there is no shell string field anywhere in the schema
([`boltrig/models/device_actions.py:119`](../../../boltrig/models/device_actions.py)
`"elif verb == "device.command.run":"`). Decision 0027 records the rejection of
`bash -lc` on this path explicitly
([`docs/decisions/0027-browser-cloud-desktop-local-agent.md:114`](../../../docs/decisions/0027-browser-cloud-desktop-local-agent.md)
`"Allow `bash -lc` in `device.command.run`."`).

### 4.3 Camera plane

`CameraBinding` is a frozen dataclass of the device's own report about one
camera: `device_id, camera_id, descriptor_fingerprint, owner_id,
connection_state, ptz_get_state, ptz_set_state, label, manufacturer, product,
transport, capabilities, evidence, updated_at, tenant_id`
([`boltrig/camera_leases.py:24`](../../../boltrig/camera_leases.py)
`"class CameraBinding:"`).

`CameraLease` mirrors `DeviceLease` with `camera_id` in place of `root_id` and no
root anywhere ([`boltrig/camera_leases.py:43`](../../../boltrig/camera_leases.py)
`"class CameraLease:"`). Its canonical payload is the exact JSON the kernel signs
and the device verifies ([`boltrig/camera_leases.py:64`](../../../boltrig/camera_leases.py)
`"def canonical_payload"`).

Closed vocabularies at the transport:

| Set | Members | Citation |
| --- | --- | --- |
| camera id shape | `^camera_[0-9A-Fa-f]{32}$` | [`boltrig/kernel/camera_agent_routes.py:19`](../../../boltrig/kernel/camera_agent_routes.py) `"_CAMERA_ID = re.compile"` |
| PTZ states | `unknown, advertised, readable, writable, proven, unsupported, invalid_descriptor` | [`boltrig/kernel/camera_agent_routes.py:20`](../../../boltrig/kernel/camera_agent_routes.py) `"_STATES = frozenset"` |
| connection states | `connected, disconnected, permission_required, unknown` | [`boltrig/kernel/camera_agent_routes.py:21`](../../../boltrig/kernel/camera_agent_routes.py) `"_CONNECTIONS = frozenset"` |
| camera verbs | `camera.ptz.get, camera.ptz.set` | [`boltrig/models/camera_actions.py:18`](../../../boltrig/models/camera_actions.py) `"CAMERA_VERBS = ("camera.ptz.get""` |
| angle bound | +/- 360,000,000 millidegrees | [`boltrig/models/camera_actions.py:21`](../../../boltrig/models/camera_actions.py) `"MAX_CAMERA_ANGLE_MILLIDEGREES = 360_000_000"` |

`camera.ptz.get` accepts exactly `{descriptor_fingerprint}`; `camera.ptz.set`
exactly `{descriptor_fingerprint, pan_millidegrees, tilt_millidegrees}`; anything
else raises `unknown_camera_action_field`
([`boltrig/models/camera_actions.py:107`](../../../boltrig/models/camera_actions.py)
`"if set(raw) != {"descriptor_fingerprint"}:"`).

### 4.4 The unwired `boltrig/camera/` discovery package

A second, separate camera model exists: `CameraDiscovery`, `Capability`,
`CapabilityState` (nine states), `CameraProfile`, `CameraProfileRegistry`,
`CameraKnowledgeCache`, `CameraBackend` (18 async methods),
`CameraDiscoveryService`. It computes a descriptor fingerprint by hashing
interface and descriptor SHAPE with current control values stripped
([`boltrig/camera/discovery.py:87`](../../../boltrig/camera/discovery.py)
`"Current focus/PTZ/exposure values must never make a new hardware family."`)
and derives `camera_id` from `vid:pid:fingerprint`
([`boltrig/camera/discovery.py:306`](../../../boltrig/camera/discovery.py)
`"camera_id = "camera_" + hashlib.sha256("`).

**No production module imports it.** Bounded search:
`rg -n "boltrig\.camera|from \.camera|CameraDiscoveryService|CameraKnowledgeCache|CameraProfileRegistry|CameraBackend" .` over the pinned tree,
2026-08-24, returns only `tests/camera/test_discovery.py`, the package's own
modules, and two unrelated `store/camera_*` hits. `CameraDiscoveryAdapter`
(`boltrig/adapters/builtin/camera.py`) is likewise built only by
`tests/camera/test_camera_adapter.py`; `boltrig/api/camera_bootstrap.py`
registers the LEASE adapter instead
([`boltrig/api/camera_bootstrap.py:19`](../../../boltrig/api/camera_bootstrap.py)
`"build_camera_lease_adapter(kernel.store, signer)"`). Both classes carry
`id = "camera"`.

### 4.5 Sensing settings

Six `user_settings` keys, all owned here and all refused by the generic settings
route: `sensing.camera.enabled`, `sensing.camera.binding`,
`sensing.camera.retention_hours`, `sensing.camera.quiet_hours`,
`sensing.presence.enabled`, `sensing.enrollment`
([`boltrig/kernel/sensing_policy.py:52`](../../../boltrig/kernel/sensing_policy.py)
`"SENSING_KEYS = frozenset({"`).

Defaults: camera off, presence off, retention 24 hours (bounded 1..168), quiet
hours 22 to 8 ([`boltrig/kernel/sensing_policy.py:78`](../../../boltrig/kernel/sensing_policy.py)
`"DEFAULT_CAMERA_ENABLED = False"`).

Capture thresholds served to the host daemons, replacing constants that used to
live in a companion repo: `thumb 64, dark_mean 12.0, change 6.0, static_diff
4.0, interval 30, dark_pause_s 900, gesture_pause_s 1800`
([`boltrig/kernel/sensing_policy.py:91`](../../../boltrig/kernel/sensing_policy.py)
`"CAPTURE_THRESHOLDS: dict[str, Any] = {"`), plus
`CONFIG_MAX_STALE_S = 3600`
([`boltrig/kernel/sensing_policy.py:106`](../../../boltrig/kernel/sensing_policy.py)
`"CONFIG_MAX_STALE_S = 3600"`).

Eleven refusal codes with user-facing copy:
[`boltrig/kernel/sensing_capability.py:61`](../../../boltrig/kernel/sensing_capability.py)
`"class SensingRefusal(StrEnum):"`. Two capability names a bundle may request:
`camera_observations`, `presence`
([`boltrig/kernel/sensing_capability.py:135`](../../../boltrig/kernel/sensing_capability.py)
`"CAPABILITIES = (CAMERA_CAPABILITY, PRESENCE_CAPABILITY)"`).

### 4.6 Emotion

`EmotionModel` carries baselines and half-lives in HOURS verbatim, need defaults
and decay, the appraisal table, a `tempo` (default 60, one model hour per real
minute), an attachment half-life in DAYS and per-emotion attachment lifts
([`boltrig/emotion/engine.py:56`](../../../boltrig/emotion/engine.py)
`"class EmotionModel:"`). The shipped data is 15 emotions and 8 needs
([`libraries/emotion/model.yaml:6`](../../../libraries/emotion/model.yaml)
`"emotions:"`), including `eros` resting at zero
([`libraries/emotion/model.yaml:25`](../../../libraries/emotion/model.yaml)
`"eros: {baseline: 0.0, half_life_h: 2}"`), and attachment lifts
`{connection: 0.3, warmth: 0.25, tenderness: 0.2, eros: 0.15}` over a 30 day
half-life ([`libraries/emotion/model.yaml:40`](../../../libraries/emotion/model.yaml)
`"half_life_days: 30"`).

`EmotionEngine` state: 15 emotions clamped 0..1, 8 needs clamped 0..10, a P/A/D
mood vector seeded `{p: 0.55, a: 0.4, d: 0.5}`, a tension scalar and an
attachment scalar ([`boltrig/emotion/engine.py:87`](../../../boltrig/emotion/engine.py)
`"self._emotions: dict[str, float] = {"`).

The observable projection is exactly ten scalars, each clamped 0..1: `fatigue,
valence, arousal, irritation, attention, social, buoyancy, luminosity, tension,
attachment` ([`boltrig/emotion/engine.py:231`](../../../boltrig/emotion/engine.py)
`"return {"` with `"attachment\": _clamp01(self._attachment),"` at line 250).

`EventRule` is the match unit: `type` equality, `where` equality, `where_not`
inequality, `has` truthiness, then `appraise` at `intensity` with an optional
per (tenant, kind) `throttle_s`
([`boltrig/emotion/tables.py:32`](../../../boltrig/emotion/tables.py)
`"class EventRule:"`). Nineteen rules ship
([`libraries/emotion/event_map.yaml:9`](../../../libraries/emotion/event_map.yaml)
`"- {type: text_delta, appraise: stream_text"`).

### 4.7 Familiar

**Genotype (identity, never changes).** `FamiliarGenotype(seed, body, palette,
markings, accessories)` with `source` pinned to `agent_capability.name.v1` and
`voice_id` pinned to `None`, derived by sha256 of the canonical capability name
alone ([`boltrig/models/familiar.py:48`](../../../boltrig/models/familiar.py)
`"def derive_familiar_genotype(capability_name: str)"`). Four bodies
`cassini, kepler, pioneer, voyager`, six palettes, four markings, three optional
accessories ([`boltrig/models/familiar.py:11`](../../../boltrig/models/familiar.py)
`"_BODIES = ("cassini", "kepler""`).

**Genes (the shader's positional array).** 32 slots, 31 claimed, order IS the
uniform layout, defaults reproduce the circle
([`familiar/genotype.h:19`](../../../familiar/genotype.h)
`"#define GENOTYPE_SLOTS 32"` and
[`familiar/genotype.h:35`](../../../familiar/genotype.h)
`"static const char *const GENOTYPE_KEYS"`). The Worker packs the same 32 floats
in the same order ([`apps/worker/src/components/familiar/FamiliarGenotype.ts:64`](../../../apps/worker/src/components/familiar/FamiliarGenotype.ts)
`"const genes = new Float32Array(["`).

**Modes and dials (decision 0030).** Six modes
`standby | listening | thinking | working | speaking | error`, five shared with
Jarvis and Ultron plus `error` which is the Familiar's alone
([`apps/worker/src/components/familiar/FamiliarState.ts:28`](../../../apps/worker/src/components/familiar/FamiliarState.ts)
`"export type FamiliarMode ="`). Precedence is failure, speaking, listening,
working, thinking, standby
([`apps/worker/src/components/familiar/FamiliarState.ts:119`](../../../apps/worker/src/components/familiar/FamiliarState.ts)
`"if (input.failed) mode = "error";"`).

`FamiliarStageState` is `{mode, level, bands?, onset?, micLevel?}`, every number
clamped 0..1 and `bands` accepted only at length 8
([`apps/worker/src/components/familiar/FamiliarState.ts:76`](../../../apps/worker/src/components/familiar/FamiliarState.ts)
`"Array.isArray(next.bands) && next.bands.length === 8"`).

`FamiliarTuning` is 24 fields, every one a number or an array of numbers so the
bench can generate its panel from the struct
([`apps/worker/src/components/canvas/familiarTuning.ts:19`](../../../apps/worker/src/components/canvas/familiarTuning.ts)
`"EVERY FIELD IS A NUMBER OR AN ARRAY OF NUMBERS."`), with shipped values lifted
from the literals they replaced
([`apps/worker/src/components/canvas/familiarTuning.ts:161`](../../../apps/worker/src/components/canvas/familiarTuning.ts)
`"export const FAMILIAR_TUNING: FamiliarTuning = {"`). Per-mode deltas plus an
arrival preset live beside it
([`apps/worker/src/components/canvas/familiarPresets.ts:59`](../../../apps/worker/src/components/canvas/familiarPresets.ts)
`"export const FAMILIAR_MODES: Record<FamiliarMode"`).

**Presentation modes.** `hero | conversation | voice | minimised`
([`apps/worker/src/components/familiar/FamiliarState.ts:40`](../../../apps/worker/src/components/familiar/FamiliarState.ts)
`"export type FamiliarPresentationMode ="`).

**Renderer status.** `{kind: "webgl2", state: mounted|running|suspended|failed|destroyed, reason?}`
([`apps/worker/src/components/familiar/FamiliarState.ts:160`](../../../apps/worker/src/components/familiar/FamiliarState.ts)
`"export interface FamiliarRendererStatus"`).

**FamiliarState v2** is a fully specified, sanitised, content-free contract of
identity, phenotype, activity, expression, voice, gaze and presentation blocks
with a monotonic `seq`
([`sdks/web/src/familiarState.ts:67`](../../../sdks/web/src/familiarState.ts)
`"export interface FamiliarStateV2"`). It has no producer and no consumer:
bounded search `rg -n "sanitizeFamiliarState|FamiliarStateV2|RESTING_FAMILIAR_STATE_V2" .`
excluding its defining file, 2026-08-24, returns only its own unit test and the
SDK barrel re-export.

### 4.8 Addons

`Addon(name, version, harness, adapter_id, consequence_hint, requirements)`,
every field beyond identity optional
([`boltrig/addons/__init__.py:90`](../../../boltrig/addons/__init__.py)
`"class Addon:"`). Validation at construction: alphanumeric name, numeric dotted
version, harness at most 4096 bytes, unique requirement ids
([`boltrig/addons/__init__.py:117`](../../../boltrig/addons/__init__.py)
`"if len(self.harness.encode("utf-8")) > MAX_ADDON_HARNESS_BYTES:"`).
`AddonRequirement(id, kind, ref, required)` with four legal kinds
`adapter, component, environment, credential_ref`
([`boltrig/addons/__init__.py:41`](../../../boltrig/addons/__init__.py)
`"REQUIREMENT_KINDS = ("adapter", "component""`); `ref` is private
evaluation input and never leaves the kernel.

One addon ships: `opbox`, version `1.0.0`, contributing an adapter id, a
riskClass consequence hint and a bounded harness
([`boltrig/addons/opbox.py:75`](../../../boltrig/addons/opbox.py)
`"ADDON = register("`).

### 4.9 Hands command

`{id, verb, args, run_id, queued_at, claimed}` plus a per-command
`asyncio.Event` and a receipt slot, TTL 30 seconds
([`boltrig/kernel/hands_registry.py:35`](../../../boltrig/kernel/hands_registry.py)
`"COMMAND_TTL_SECONDS = 30.0"`).

---

## 5. Control flow

### 5.1 Device enrollment (IMPLEMENTED)

1. `POST /v1/devices/enrollment/start` with a `label`. Refuses any non-human
   actor tier: [`boltrig/kernel/device_routes.py:72`](../../../boltrig/kernel/device_routes.py)
   `"return _error("human_required", 403)"`.
   **Failure:** no lease signer configured returns 503 `device_leases_unavailable`
   before anything else ([`boltrig/kernel/device_routes.py:75`](../../../boltrig/kernel/device_routes.py)
   `"return _error("device_leases_unavailable", 503)"`).
2. The kernel mints an opaque scoped token, stores only its sha256, and returns
   the code, the expiry, a verification URI and the Ed25519 verifier view
   ([`boltrig/kernel/device_routes.py:81`](../../../boltrig/kernel/device_routes.py)
   `"code = mint_scoped_token("`, and
   [`boltrig/kernel/device_routes.py:88`](../../../boltrig/kernel/device_routes.py)
   `"authorization_code_hash=token_digest(code),"`).
   **Failure:** duplicate id returns 409 `enrollment_conflict`.
3. `POST /v1/device-agent/enrollment/complete` with `{authorization_code,
   device_public_key}`. The code is parsed for kind `device_enrollment`; the
   public key must decode to exactly 32 raw bytes
   ([`boltrig/kernel/device_route_support.py:305`](../../../boltrig/kernel/device_route_support.py)
   `"raise ValueError("invalid_device_public_key")"`).
   **Failure:** any parse error returns 401 `invalid_or_expired_enrollment`
   ([`boltrig/kernel/device_agent_routes.py:48`](../../../boltrig/kernel/device_agent_routes.py)
   `"return _error("invalid_or_expired_enrollment", 401)"`).
4. A device row is created with `owner_id=""` and a fresh session token, and the
   store's `complete_device_enrollment` is the single atomic consume
   ([`boltrig/kernel/device_agent_routes.py:60`](../../../boltrig/kernel/device_agent_routes.py)
   `"completed = await kernel.store.complete_device_enrollment("`).
   **Failure:** a consumed or expired enrollment returns `None` and the route
   answers 401.
5. `audit_device` writes an audit row with actor `device:{id}` and actor tier
   `ephemeral` ([`boltrig/kernel/device_route_support.py:288`](../../../boltrig/kernel/device_route_support.py)
   `"actor_tier="human" if not actor.startswith("device:") else "ephemeral""`).

Decision 0027 amends the human-facing half of this: the signed desktop consumes
a short-lived server bootstrap rather than a pasted code
([`docs/decisions/0027-browser-cloud-desktop-local-agent.md:75`](../../../docs/decisions/0027-browser-cloud-desktop-local-agent.md)
`"Users never copy or paste an"`, the sentence finishing "enrollment code" on line 76).

### 5.2 Device lease issuance (IMPLEMENTED)

1. An agent dispatches one of the four `device.*` verbs through the ordinary
   chokepoint. All four are HIGH consequence, 30 per minute per tenant,
   idempotency `cacheable`
   ([`boltrig/adapters/builtin/device.py:109`](../../../boltrig/adapters/builtin/device.py)
   `""consequence": "high","`).
2. The consequence gate raises a HITL approval. Before the approval is shown,
   `DeviceLeaseIssuer.resource_context` publishes only public, authority-bearing
   state (device id, root id, root scope, command flag, verifier key id)
   ([`boltrig/device_leases.py:49`](../../../boltrig/device_leases.py)
   `"Return only public, authority-bearing device state for HITL binding."`).
   **Failure branches, in order:** no signer 503 `device_leases_unavailable`;
   malformed action 400 with the ValueError text; unknown or revoked device or
   root 404 `device_or_root_not_found`; stale verifier 409
   `device_verifier_stale`; write to a read-only root 403 `root_is_read_only`;
   command on a root without `command_enabled` 403 `command_disabled`; a
   cancelled run 409 `run_cancelled`
   ([`boltrig/device_leases.py:65`](../../../boltrig/device_leases.py)
   `"raise DeviceLeaseIssueError("device_or_root_not_found", 404)"` through line 74).
3. On approval, `materialize` re-runs `resource_context`, recomputes the digest,
   then demands ALL of: a HITL request that is CONSUMED and of type APPROVAL,
   verb equality, `hmac.compare_digest` on the action digest, the owner being the
   requester or the on-behalf subject, the respondent NOT being either of those,
   `compare_digest(response.respondent, approved_by)`, an approving decision word,
   and a non-expired timeout. Any one failing yields 403
   `consumed_exact_action_approval_required`
   ([`boltrig/device_leases.py:134`](../../../boltrig/device_leases.py)
   `"raise DeviceLeaseIssueError("`).
4. The lease is signed Ed25519 over the canonical bytes with the signature field
   emptied ([`boltrig/kernel/device_crypto.py:105`](../../../boltrig/kernel/device_crypto.py)
   `"def sign(self, lease: DeviceLease) -> DeviceLease:"`) and persisted with a
   conditional INSERT that re-checks every predicate in SQL
   ([`boltrig/store/camera_pg.py:65`](../../../boltrig/store/camera_pg.py)
   `"INSERT INTO camera_leases"` is the camera twin; the device twin is
   [`boltrig/store/device_pg.py:156`](../../../boltrig/store/device_pg.py)
   `"INSERT INTO device_leases"`).
   **Failure:** the INSERT matching nothing returns 409
   `device_lease_not_materialized`.

### 5.3 Device lease claim and settlement (IMPLEMENTED)

1. The enrolled agent polls `GET /v1/device-agent/{device_id}/leases` with its
   session bearer ([`boltrig/kernel/device_agent_routes.py:79`](../../../boltrig/kernel/device_agent_routes.py)
   `"async def pending_leases"`). The Tauri agent polls every 3 seconds
   ([`apps/worker/src-tauri/src/device_agent.rs:29`](../../../apps/worker/src-tauri/src/device_agent.rs)
   `"const POLL_INTERVAL: Duration = Duration::from_secs(3);"`).
2. `POST .../leases/{lease_id}/claim` with the lease signature. The kernel
   re-verifies the signature with its own signer before accepting the claim
   ([`boltrig/kernel/device_agent_routes.py:104`](../../../boltrig/kernel/device_agent_routes.py)
   `"or not signer.verify(lease)"`).
   **Failure:** 403 `invalid_lease_signature`; a lease already claimed or expired
   returns 409 `lease_unavailable`.
3. The store performs a compare-and-set to `claimed`, stamping a claim token
   digest and a claim expiry bounded to 5 minutes.
4. `POST .../leases/{lease_id}/receipt` with `{claim_token, status, receipt}`.
   `status` must be `completed` or `failed`; the receipt must be a JSON object
   whose canonical encoding is at most 32,000 bytes
   ([`boltrig/kernel/device_agent_routes.py:152`](../../../boltrig/kernel/device_agent_routes.py)
   `"return _error("receipt_too_large")"`).
   **Failure:** anything not matching the stored claim token digest, or a claim
   past its expiry, returns 409 `claim_unavailable`.
5. The owning human reads the lease back through
   `GET /v1/devices/{device_id}/leases`, which projects a bounded receipt
   summary: file byte size and digest, a validated single-level directory listing
   whose every entry path must equal `relative_path/name`, or a command duration
   and exit code with `output_captured: False` pinned
   ([`boltrig/kernel/device_route_support.py:200`](../../../boltrig/kernel/device_route_support.py)
   `""output_captured": False,"`).

### 5.4 Camera binding publish (IMPLEMENTED)

1. The device agent enumerates cameras natively and publishes each as a binding:
   `POST /v1/device-agent/{device_id}/camera-bindings`, device-session
   authenticated ([`boltrig/kernel/camera_agent_routes.py:186`](../../../boltrig/kernel/camera_agent_routes.py)
   `"async def publish_binding"`).
2. `_binding_from_body` validates the camera id shape, a 64 hex fingerprint, the
   closed state sets, and a capabilities/evidence pair whose canonical encoding
   is at most 64,000 bytes with at most 64 evidence entries
   ([`boltrig/kernel/camera_agent_routes.py:96`](../../../boltrig/kernel/camera_agent_routes.py)
   `"if len(encoded) > 64_000 or len(evidence) > 64:"`).
   **The proof clause:** claiming `ptz_set_state == "proven"` without the
   evidence string `bounded_uvc_set_readback_frame_change_and_exact_restoration`
   is refused ([`boltrig/kernel/camera_agent_routes.py:88`](../../../boltrig/kernel/camera_agent_routes.py)
   `"raise ValueError("camera_physical_proof_evidence_required")"`).
   **Failure:** the reason is filtered through a seven-member allow-list, so an
   unregistered ValueError becomes `invalid_request`
   ([`boltrig/kernel/camera_agent_routes.py:51`](../../../boltrig/kernel/camera_agent_routes.py)
   `"def _validation_reason"`).
3. The store upsert re-derives `owner_id` from the `devices` row in SQL and
   refuses if the device is revoked or owned by someone else
   ([`boltrig/store/camera_pg.py:15`](../../../boltrig/store/camera_pg.py)
   `"SELECT $1,$2,$3,$4,d.owner_id"`).
   **Failure:** 409 `camera_binding_unavailable`.
4. The publish is audited as `camera.binding.publish`.

### 5.5 Camera lease issuance, claim and native execution (IMPLEMENTED)

1. `camera.ptz.get` / `camera.ptz.set` dispatch through the chokepoint. Both are
   HIGH consequence, 30 per minute per tenant
   ([`boltrig/adapters/builtin/camera_leases.py:30`](../../../boltrig/adapters/builtin/camera_leases.py)
   `""consequence": "high","`).
2. `approval_context` requires a binding that is `connected`, whose `ptz_get_state`
   is `readable` or `proven`, whose `ptz_set_state` is `proven` when the verb is
   `camera.ptz.set`, and whose `descriptor_fingerprint` equals the one inside the
   action. Any mismatch is 409 `camera_binding_not_proven`
   ([`boltrig/camera_leases.py:155`](../../../boltrig/camera_leases.py)
   `"raise CameraLeaseIssueError("camera_binding_not_proven", 409)"`).
3. `execute` refuses unless the dispatcher handed it a 64 character approval
   fingerprint, an approval id, an approver, and a resource context that still
   equals the one the approval was raised against
   ([`boltrig/adapters/builtin/camera_leases.py:136`](../../../boltrig/adapters/builtin/camera_leases.py)
   `""exact_approval_evidence_missing""`).
4. `materialize` applies the same nine-clause approval test as the device path,
   then signs and inserts. The SQL insert re-derives every clause including
   `NOT EXISTS (SELECT 1 FROM camera_leases prior WHERE prior.approval_id=$9)`
   and a 120 second expiry window
   ([`boltrig/store/camera_pg.py:99`](../../../boltrig/store/camera_pg.py)
   `"AND $11 > now() AND $11 <= now() + interval '120 seconds'"`).
5. The device claims and executes. The Rust verifier independently re-checks the
   envelope: version 1, status `issued`, matching device id, matching signing key
   id, valid identifiers, a total validity window of at most 3 minutes, and an
   `issued_at` no more than 30 seconds in the future
   ([`apps/worker/src-tauri/src/camera_protocol.rs:85`](../../../apps/worker/src-tauri/src/camera_protocol.rs)
   `"|| expires_at - issued_at > time::Duration::minutes(3)"`).
   It recomputes the action digest and compares in constant time
   ([`apps/worker/src-tauri/src/camera_protocol.rs:78`](../../../apps/worker/src-tauri/src/camera_protocol.rs)
   `"camera_lease_action_digest_mismatch"`).
6. Before touching the hardware, the runtime compares the lease's fingerprint to
   the live camera's and refuses `camera_descriptor_changed`
   ([`apps/worker/src-tauri/src/camera_discovery.rs:488`](../../../apps/worker/src-tauri/src/camera_discovery.rs)
   `"return Err("camera_descriptor_changed".to_string());"`).
7. On success it builds a receipt pinning `hid_reports_sent: false` and
   `zoom_or_focus_writes: false`
   ([`apps/worker/src-tauri/src/camera_discovery.rs:509`](../../../apps/worker/src-tauri/src/camera_discovery.rs)
   `"receipt.insert("hid_reports_sent".to_string(), json!(false));"`).
   **Failure:** any error becomes a `failed` terminal status carrying
   `{"code": reason}` ([`apps/worker/src-tauri/src/device_agent.rs:531`](../../../apps/worker/src-tauri/src/device_agent.rs)
   `"Err(reason) => ("failed".to_string(), json!({"code": reason})),"`).
8. The agent holds at most ONE pending camera claim at a time and persists it
   before executing, so a crash mid-execution still settles on the next cycle
   ([`apps/worker/src-tauri/src/device_agent.rs:512`](../../../apps/worker/src-tauri/src/device_agent.rs)
   `"agent.pending_camera_claim = Some(PendingClaim {"`).

**Identity derivation, as shipped.** `camera_id` and `descriptor_fingerprint` are
BOTH sha256 over a USB topology string `"vid:pid:bus:port.path"`, and the id is
the first 32 hex characters of that digest
([`apps/worker/src-tauri/src/camera_uvc.m:202`](../../../apps/worker/src-tauri/src/camera_uvc.m)
`""%04x:%04x:%u:", vendor, product,"` and
[`apps/worker/src-tauri/src/camera_discovery.rs:675`](../../../apps/worker/src-tauri/src/camera_discovery.rs)
`"let camera_id = format!("camera_{}", &descriptor_fingerprint[..32]);"`).
Moving the camera to a different USB port therefore changes its identity, which
the runbook records as an operational consequence
([`docs/ACTIVATE-SENSING-RUNBOOK.md:198`](../../../docs/ACTIVATE-SENSING-RUNBOOK.md)
`"moving the camera to a different USB port changes its identity."`).

### 5.6 Sensing config and consent (IMPLEMENTED)

1. The human sets consent through `PUT /v1/me/sensing/camera`. The route demands
   an interactive human credential, not merely a human tier
   ([`boltrig/kernel/sensing_routes.py:55`](../../../boltrig/kernel/sensing_routes.py)
   `"return p.actor_tier == "human" and is_interactive_credential("`).
   **Failure:** 403 `an interactive human session is required`. A PAT is refused
   here even though it satisfies enrollment
   ([`docs/ACTIVATE-SENSING-RUNBOOK.md:214`](../../../docs/ACTIVATE-SENSING-RUNBOOK.md)
   `"A PAT will not do."`).
2. A binding naming a camera nobody published is refused at WRITE time with 409
   `camera_binding_unavailable`
   ([`boltrig/kernel/sensing_routes.py:132`](../../../boltrig/kernel/sensing_routes.py)
   `"return _error("camera_binding_unavailable", 409)"`).
3. Every write answers with the whole settled state rather than an ack
   ([`boltrig/kernel/sensing_routes.py:63`](../../../boltrig/kernel/sensing_routes.py)
   `"Every write answers with the whole settled state, not an ack."`).
4. `PUT /v1/me/sensing/presence` refuses `enabled: true` with 409 when there is no
   enrolment or no calibrated threshold
   ([`boltrig/kernel/sensing_routes.py:160`](../../../boltrig/kernel/sensing_routes.py)
   `"return _error(blocker, 409)"`).
5. `DELETE /v1/me/sensing/enrollment` forgets the face by writing `None` and
   switches presence off in the same request
   ([`boltrig/kernel/sensing_routes.py:179`](../../../boltrig/kernel/sensing_routes.py)
   `"await persist_presence_enabled(k.store, p.tenant_id, p.subject, False)"`).
6. The host daemon reads its policy at
   `GET /v1/device-agent/{device_id}/sensing-config`, authenticated as the DEVICE
   and answered for the device's OWNER
   ([`boltrig/kernel/camera_agent_routes.py:288`](../../../boltrig/kernel/camera_agent_routes.py)
   `"Authenticated as the DEVICE, and answered for the device's OWNER"`).
   The config never reports presence enabled without a threshold
   ([`boltrig/kernel/sensing_policy.py:271`](../../../boltrig/kernel/sensing_policy.py)
   `"settings["presence"]["enabled"] and enrollment.get("threshold") is not None"`).
7. The host publishes the enrolment as METADATA ONLY at
   `POST /v1/device-agent/{device_id}/sensing-enrollment`; vectors stay on the
   machine ([`boltrig/kernel/camera_agent_routes.py:303`](../../../boltrig/kernel/camera_agent_routes.py)
   `"METADATA ONLY -- digest, sample count, the room-calibrated threshold"`).
   **Failure:** an enrolment with no calibrated threshold in `(0, 1]` is refused
   `sensing_enrollment_requires_a_calibrated_threshold`.
8. A character asks `GET /v1/sensing/capability?capability=...`, answered with a
   named refusal and 409 (not 403) when consent is off
   ([`boltrig/kernel/sensing_routes.py:217`](../../../boltrig/kernel/sensing_routes.py)
   `"status = 200 if decision["status"] == "granted" else 409"`).

**The declaration gap, recorded by the code itself.** The route is authenticated
as the USER and nothing on the request names a character, so declaration is NOT
enforced: an undeclared character asking with the camera on is told `granted`
([`boltrig/kernel/sensing_capability.py:19`](../../../boltrig/kernel/sensing_capability.py)
`"It does not enforce declaration, and it cannot."`). The Worker honours
declaration one layer up by asking only for the ids in the character's
`wantsSensing` ([`apps/worker/src/components/StageBody.tsx:166`](../../../apps/worker/src/components/StageBody.tsx)
`"const sensing = useSensing(character.wantsSensing);"`), re-asked every 30
seconds and never cached
([`apps/worker/src/components/StageBody.tsx:136`](../../../apps/worker/src/components/StageBody.tsx)
`"const timer = window.setInterval(ask, 30_000);"`). That is a constraint on the
Stage, not a boundary, since a character add-in shares the Worker's JS realm.

### 5.7 Emotion relay and phenotype publication (IMPLEMENTED)

1. `Kernel.__init__` wraps whatever transport composition chose:
   `build_emotion_relay(backend=event_relay)`.
2. `_enabled()` decides: `BOLTRIG_EMOTION=0` off, `=1` on, otherwise `orbctl` on
   PATH ([`boltrig/emotion/relay.py:352`](../../../boltrig/emotion/relay.py)
   `"def _enabled() -> bool:"`).
   **Failure:** no `XDG_RUNTIME_DIR`, unloadable tables, or ANY exception returns
   the plain relay ([`boltrig/emotion/relay.py:388`](../../../boltrig/emotion/relay.py)
   `"except Exception:  # noqa: BLE001 - the emotion path must never break kernel bring-up"`).
3. Every `publish` forwards to the backend FIRST, then calls `_react` inside a
   bare `try/except: pass` ([`boltrig/emotion/relay.py:105`](../../../boltrig/emotion/relay.py)
   `"self._react(tenant_id, event)"`).
4. `_react` special-cases `emotion_reset` before rule matching: it replaces the
   tenant's engine with a fresh one at model baselines AND drops the persisted
   restore snapshot so a restart cannot resurrect the old mood
   ([`boltrig/emotion/relay.py:229`](../../../boltrig/emotion/relay.py)
   `"self._engines[tenant_id] = EmotionEngine(self._model, time.time())"`).
5. Otherwise the first matching rule wins, is throttled per (tenant, kind), and
   appraises into the tenant's engine under one lock
   ([`boltrig/emotion/relay.py:247`](../../../boltrig/emotion/relay.py)
   `"First matching rule wins (the event_map.yaml order is the precedence)."`).
6. A daemon publisher thread ticks every `publish_interval` (default 0.5 s),
   writes the phenotype file each tick and the tenant state file every 20th
   ([`boltrig/emotion/relay.py:308`](../../../boltrig/emotion/relay.py)
   `"if tick % _STATE_EVERY_TICKS == 0:"`).
7. Both writes are atomic through a UNIQUE `mkstemp` plus `chmod 0644` plus
   `os.replace`, deliberately not a fixed tmp name
   ([`boltrig/emotion/relay.py:340`](../../../boltrig/emotion/relay.py)
   `"fd, tmp = tempfile.mkstemp(prefix=f".{path.name}-", dir=str(path.parent))"`).
   The docstring records why: a fixed name under a 0777 bind mount is an
   arbitrary-file-write primitive through a pre-created symlink.
8. Which tenant's phenotype gets published: the engine named by `self._tenant`
   (default `"default"`), else the single engine if exactly one exists, else
   nothing ([`boltrig/emotion/relay.py:304`](../../../boltrig/emotion/relay.py)
   `"if engine is None and len(self._engines) == 1:"`).

### 5.8 The phenotype projection route (IMPLEMENTED)

1. `GET /v1/familiar/phenotype` reads `$XDG_RUNTIME_DIR/boltrig-phenotype.json`.
2. Refusals, all answering the resting shape `{"v": 1, "fresh": false,
   "phenotype": null}`: no runtime dir; file over 4096 bytes; mtime older than
   5 seconds; malformed JSON; no `phenotype` object; no whitelisted scalar
   survived ([`boltrig/kernel/familiar_phenotype_routes.py:67`](../../../boltrig/kernel/familiar_phenotype_routes.py)
   `"except Exception:  # noqa: BLE001 - fail toward resting, never toward a fault"`).
3. Surviving scalars are whitelisted to the ten names and clamped 0..1; non-finite
   values are dropped ([`boltrig/kernel/familiar_phenotype_routes.py:62`](../../../boltrig/kernel/familiar_phenotype_routes.py)
   `"if isinstance(value, (int, float)) and math.isfinite(value):"`).
4. `POST /v1/familiar/emotion/reset` and `POST /v1/familiar/emotion/adopted`
   publish plain relay frames on the `emotion` stream. The adoption id is bounded
   to 64 characters ([`boltrig/kernel/familiar_phenotype_routes.py:109`](../../../boltrig/kernel/familiar_phenotype_routes.py)
   `"if len(character) > _CHARACTER_ID_MAX:"`); the appraisal is throttled 60
   seconds per (tenant, kind) so flicking skins cannot pump mood
   ([`libraries/emotion/event_map.yaml:39`](../../../libraries/emotion/event_map.yaml)
   `"appraise: character_adopted, intensity: 1.0, throttle_s: 60"`).

### 5.9 Familiar Stage mount and the renderer ladder (IMPLEMENTED)

1. `<FamiliarStage mode state phenotype genotype label />` renders a host div with
   `role="img"`, a data attribute for the chosen renderer, and a SIBLING
   `aria-live="polite"` region carrying the spoken mode
   ([`apps/worker/src/components/familiar/FamiliarStage.tsx:71`](../../../apps/worker/src/components/familiar/FamiliarStage.tsx)
   `"<span aria-live="polite" className="familiar-stage-status">"`).
2. `useFamiliarRenderer` mounts ONCE, seeding the genotype before link so the
   first frames carry identity
   ([`apps/worker/src/components/familiar/useFamiliarRenderer.ts:48`](../../../apps/worker/src/components/familiar/useFamiliarRenderer.ts)
   `"renderer.setGenotype(genotype);"`).
3. The renderer kind starts `pending` (reported as `aria-busy`), becomes `webgl2`
   on first paint, and becomes `badge` the moment the renderer reports `failed`
   ([`apps/worker/src/components/familiar/useFamiliarRenderer.ts:52`](../../../apps/worker/src/components/familiar/useFamiliarRenderer.ts)
   `"if (renderer.status().state === "failed") setKind("badge");"`).
   **Failure branches inside the renderer:** no WebGL2 context, or a link/compile
   throw, both call `fail()` rather than rewriting the look
   ([`apps/worker/src/components/familiar/FamiliarWebGLRenderer.ts:122`](../../../apps/worker/src/components/familiar/FamiliarWebGLRenderer.ts)
   `"never rewrite the look to survive a failure"`).
4. A stale projection is handed over as `null`, not as its last value, so an
   absent relay reads as a calm creature
   ([`apps/worker/src/components/familiar/useFamiliarRenderer.ts:72`](../../../apps/worker/src/components/familiar/useFamiliarRenderer.ts)
   `"phenotype?.fresh && phenotype.phenotype ? phenotype.phenotype : null,"`).
5. `setMode("minimised")` suspends the frame loop; anything else resumes it
   ([`apps/worker/src/components/familiar/FamiliarWebGLRenderer.ts:158`](../../../apps/worker/src/components/familiar/FamiliarWebGLRenderer.ts)
   `"if (mode === "minimised") this.suspend();"`).
6. The bench drives the SHIPPED renderer through `setTuning` / `currentTuning` /
   `transitionTo` / `intro` / `replay` / public `frame`, so a tuned recipe cannot
   drift from what ships
   ([`apps/worker/src/components/familiar/FamiliarWebGLRenderer.ts:165`](../../../apps/worker/src/components/familiar/FamiliarWebGLRenderer.ts)
   `"setTuning(next: FamiliarTuning): void {"`).
7. Which body reads the phenotype is per character, not per installation:
   `StageBody` hands `null` to any character whose bundle does not declare it
   ([`apps/worker/src/components/StageBody.tsx:173`](../../../apps/worker/src/components/StageBody.tsx)
   `"const inner = character.readsPhenotype ? (phenotype ?? null) : null;"`).

The ladder itself is decision 0025's table: CSS `FamiliarBadge` as the floor,
`webgl2` as the universal Stage renderer, `unreal-local`/`unreal-remote` DEFERRED
([`docs/decisions/0025-familiar-stage-renderer-ladder.md:36`](../../../docs/decisions/0025-familiar-stage-renderer-ladder.md)
`"| CSS `FamiliarBadge` | floor: message avatars"`). No Unreal code exists in this
tree (bounded: `rg -ni "unreal" apps/ sdks/ boltrig/`, 2026-08-24, hits only ADR
prose and comments).

### 5.10 Voluntary expression, `familiar.express` (IMPLEMENTED)

1. `familiar.express` is a normal builtin adapter verb, LOW consequence, 120 per
   minute, idempotency `disabled` because a gesture must never be replayed
   ([`boltrig/adapters/builtin/familiar.py:109`](../../../boltrig/adapters/builtin/familiar.py)
   `"idempotency_mode="disabled","`).
2. Its binding is a closed gesture enum of eight, an optional 0..1 intensity and
   a `ttl_s` capped at 15, `additionalProperties: false`
   ([`boltrig/adapters/builtin/familiar.py:40`](../../../boltrig/adapters/builtin/familiar.py)
   `"GESTURES = ("look", "pulse", "flinch""`).
3. The handler is the ONLY writer of `$XDG_RUNTIME_DIR/boltrig-express.json`,
   written atomically and chmod 0644
   ([`boltrig/adapters/builtin/familiar.py:74`](../../../boltrig/adapters/builtin/familiar.py)
   `"os.chmod(tmp, 0o644)"`).
   **Failure:** no runtime dir, or any write error, yields
   `{"gesture": ..., "delivered": false}` and the governed act still stands
   ([`boltrig/adapters/builtin/familiar.py:143`](../../../boltrig/adapters/builtin/familiar.py)
   `"delivered = False  # cosmetic delivery is best-effort"`).
4. The surface detects a NEW gesture by file mtime, so the handler reads no clock
   ([`boltrig/adapters/builtin/familiar.py:131`](../../../boltrig/adapters/builtin/familiar.py)
   `"No clock read here: the surface detects a NEW gesture by the file's mtime"`).
   The desktop reader ignores a record older than 5 seconds and obeys
   `FAMILIAR_EXPRESS=0` ([`familiar/main.c:1171`](../../../familiar/main.c)
   `"if (difftime(time(NULL), st.st_mtime) > PHENO_FRESH_S) return 0;"`).

### 5.11 Desktop hands (IMPLEMENTED, opt-in)

1. Registration requires `BOLTRIG_DESKTOP_HANDS` truthy on every boot path
   ([`boltrig/api/bootstrap.py:137`](../../../boltrig/api/bootstrap.py)
   `"return is_truthy(os.environ.get("BOLTRIG_DESKTOP_HANDS"))"`), and the same
   flag gates attaching the registry
   ([`boltrig/api/bootstrap.py:399`](../../../boltrig/api/bootstrap.py)
   `"kernel.hands_registry = HandsRegistry()"`).
2. Six verbs with their risk table:

| verb | consequence | rate | idempotency |
| --- | --- | --- | --- |
| `desktop.window.list` | low | 120/min/tenant | cacheable |
| `desktop.window.focus` | low | 60/min/tenant | disabled |
| `desktop.window.move` | high | 60/min/tenant | disabled |
| `desktop.window.arrange` | high | 60/min/tenant | disabled |
| `desktop.workspace.switch` | low | 60/min/tenant | disabled |
| `desktop.app.launch` | high | 60/min/tenant | disabled |

[`boltrig/adapters/builtin/desktop.py:78`](../../../boltrig/adapters/builtin/desktop.py)
`"verb_id="desktop.window.list","` through line 192. Every state-changing verb
is `disabled` so a replayed receipt cannot claim a delivery that did not happen
([`boltrig/adapters/builtin/desktop.py:105`](../../../boltrig/adapters/builtin/desktop.py)
`"changes host state: never serve a focus from a replay cache"`).
3. The handler enqueues a command and awaits the receipt for 8 seconds, which is
   deliberately shorter than the registry's 30 second TTL
   ([`boltrig/adapters/builtin/desktop.py:41`](../../../boltrig/adapters/builtin/desktop.py)
   `"_DEFAULT_WAIT_S = 8.0"`).
   **Failure:** timeout returns `{"status": "executor_offline", "delivered": false}`
   with the audit row standing.
4. `GET /v1/hands/commands` sweeps expired commands, then claims each returned
   command mark-on-read with no await between read and mark
   ([`boltrig/kernel/desktop_routes.py:58`](../../../boltrig/kernel/desktop_routes.py)
   `"No awaits between the"`).
   **Failure:** no registry returns 503 `hands_unavailable`.
5. `POST /v1/hands/commands/{cmd_id}/receipt` requires status in `{ok, error}`,
   resolves the waiting dispatch and audits `desktop.hands.receipt`.
   **Failure:** an unknown or expired id returns 404 and is deliberately NOT
   audited ([`boltrig/kernel/desktop_routes.py:82`](../../../boltrig/kernel/desktop_routes.py)
   `"do not audit a no-op as execution"`).

### 5.12 Addon activation and product name (IMPLEMENTED)

1. `boltrig/addons/__init__.py` self-registers the builtin `opbox` addon at
   import, then loads any entry-point addons
   ([`boltrig/addons/__init__.py:332`](../../../boltrig/addons/__init__.py)
   `"load_builtin_addons()"`).
2. `active_addons()` reads `BOLTRIG_ADDONS` and RAISES on a name nothing
   registers ([`boltrig/addons/__init__.py:167`](../../../boltrig/addons/__init__.py)
   `"f"{ENV_VAR} names unregistered addon(s)"`). The ASGI entry point calls it
   first so a typo fails the boot
   ([`boltrig/api/asgi.py:26`](../../../boltrig/api/asgi.py)
   `"_ADDONS = active_addons()"`).
3. An entry point that would replace an already registered name is refused,
   because a squatter would inherit the displaced addon's adapter claim
   ([`boltrig/addons/__init__.py:311`](../../../boltrig/addons/__init__.py)
   `"would replace the already ""`).
4. The birth profile version composes rather than forks:
   `composed_version("1.1.0", addons)` produces `1.1.0+opbox-1.0.0`, resolved ONCE
   at import so the text and the version cannot drift
   ([`boltrig/fleet/infrastructure/codex_kernel_tools_phase.py:112`](../../../boltrig/fleet/infrastructure/codex_kernel_tools_phase.py)
   `"KERNEL_TOOLS_PROFILE_VERSION = composed_version("`).
5. Consequence hints are read from EVERY REGISTERED addon, not only active ones,
   and the HIGHEST wins, because a reading can only raise a tier
   ([`boltrig/addons/__init__.py:208`](../../../boltrig/addons/__init__.py)
   `"The HIGHEST consequence any addon reads off"`).
6. `product_name()` returns `"Opbox Agents"` when the `opbox` addon is active and
   `"Boltrig"` otherwise, served at `GET /v1/branding`
   ([`boltrig/branding.py:39`](../../../boltrig/branding.py)
   `"return OPBOX_AGENTS if any(a.name == _OPBOX_ADDON for a in active) else BOLTRIG"`,
   route at [`boltrig/kernel/health_routes.py:23`](../../../boltrig/kernel/health_routes.py)
   `"@app.get("/v1/branding")"`). This IS decision 0035 applied to the product
   name: a runtime signal rather than a baked build flag
   ([`boltrig/branding.py:8`](../../../boltrig/branding.py)
   `"WHY THIS IS DERIVED FROM THE ADDON AND NOT FROM A BUILD FLAG."`).

### 5.13 The desktop familiar (SEAM plus IMPLEMENTED surface)

`familiar/` is a self-contained C/GLES3 wayland layer-shell client. It reads the
phenotype file every 15 frames, smooths each scalar toward its target with a
0.9 second time constant, and hands nine uniforms to the shader
([`familiar/main.c:82`](../../../familiar/main.c)
`"#define STATE_POLL_FRAMES  15"`). A phenotype older than 5 seconds, or
`FAMILIAR_PHENO=0`, falls back to `PHENO_IDLE`
([`familiar/main.c:118`](../../../familiar/main.c)
`"static const Phenotype PHENO_IDLE = {"`).

**It consumes NINE scalars, not ten.** The `Phenotype` struct has no
`attachment` field ([`familiar/main.c:110`](../../../familiar/main.c)
`"float valence, arousal, irritation, fatigue, attention,"`), while the Worker
projection whitelists ten
([`boltrig/kernel/familiar_phenotype_routes.py:30`](../../../boltrig/kernel/familiar_phenotype_routes.py)
`"PHENOTYPE_SCALARS = ("`). Decision 0024's attachment scalar therefore reaches
the browser body and not the desktop one; the ADR anticipates exactly this
("downstream consumers that ignore it are unaffected (additive, P9)").

---

## 6. Data

### 6.1 Tables owned here

**`device_enrollments`** (migration 0042): `id, tenant_id, owner_id, label,
authorization_code_hash, expires_at, consumed_at, created_at`. PK
`(tenant_id, id)`, UNIQUE `(tenant_id, authorization_code_hash)`, CHECK the hash
is 64 hex ([`migrations/versions/0042_desktop_devices.py:19`](../../../migrations/versions/0042_desktop_devices.py)
`"CREATE TABLE IF NOT EXISTS device_enrollments"`).

**`devices`**: adds `public_key, public_key_fingerprint, lease_verify_key_id,
availability_mode, presence, session_token_hash, session_expires_at,
last_seen_at, revoked_at`. UNIQUE `(tenant_id, session_token_hash)` so a token
digest is globally unique per tenant. Index `devices_owner_idx` on
`(tenant_id, owner_id, created_at)`.

**`device_roots`**: `scope` CHECK `('read','read_write')`, `command_enabled`,
`git_enabled`, UNIQUE `(tenant_id, id, device_id)` so a lease's composite FK can
bind root to device.

**`device_leases`**: PK `(tenant_id, id)`, UNIQUE `(tenant_id, approval_id)`
(one approval, one lease, at the schema level), FKs to `devices`, to
`(device_roots.tenant_id, id, device_id)`, and to `hitl_requests` with
`ON DELETE RESTRICT` so an approval cannot be deleted out from under a lease.
Index `device_leases_pending_idx` on `(tenant_id, device_id, status, issued_at)`.
The verb CHECK started at three verbs and was widened to four by migration 0072,
whose downgrade REFUSES while any `device.file.list` lease exists
([`migrations/versions/0072_device_workspace_snapshots.py:51`](../../../migrations/versions/0072_device_workspace_snapshots.py)
`"RAISE EXCEPTION 'device workspace snapshot leases still exist'"`).

**`camera_bindings`** (migration 0068): PK `(tenant_id, device_id, camera_id)`,
`descriptor_fingerprint` CHECK 64 hex, connection and both PTZ states CHECKed
against their closed sets, `capabilities` CHECK `jsonb_typeof = 'object'`,
`evidence` CHECK `jsonb_typeof = 'array'`, FK to `devices` ON DELETE CASCADE,
index on `(tenant_id, owner_id, device_id, camera_id)`
([`migrations/versions/0068_camera_uvc_leases.py:13`](../../../migrations/versions/0068_camera_uvc_leases.py)
`"CREATE TABLE IF NOT EXISTS camera_bindings"`).

**`camera_leases`**: PK `(tenant_id, id)`, UNIQUE `(tenant_id, approval_id)`,
verb CHECK exactly the two PTZ verbs, status CHECK five values, digest and claim
hash CHECK 64 hex, FK to the binding triple ON DELETE CASCADE, FK to
`hitl_requests` ON DELETE RESTRICT, index
`(tenant_id, device_id, status, issued_at)`.

**Row level security.** All six tables ENABLE and FORCE RLS with a
`tenant_isolation` policy on `current_setting('app.tenant_id')` for both USING
and WITH CHECK ([`migrations/versions/0068_camera_uvc_leases.py:75`](../../../migrations/versions/0068_camera_uvc_leases.py)
`"'CREATE POLICY tenant_isolation ON %I '"`). The device routes set and clear the
tenant around store calls
([`boltrig/kernel/device_route_support.py:48`](../../../boltrig/kernel/device_route_support.py)
`"set_current_tenant(tenant_id)"`).

**Consent lives in `user_settings`, deliberately not a new table.**
[`boltrig/kernel/sensing_policy.py:19`](../../../boltrig/kernel/sensing_policy.py)
`"WHY user_settings AND NOT A NEW TABLE."` The face enrolment is a row in that
table, excluded from bundle export and deliberately NOT excluded from the user's
own data export ([`boltrig/kernel/sensing_policy.py:70`](../../../boltrig/kernel/sensing_policy.py)
`"Deliberately NOT excluded from ``GET /v1/me/export``"`).

### 6.2 Files (not tables)

| Path | Writer | Reader | Shape | Freshness |
| --- | --- | --- | --- | --- |
| `$XDG_RUNTIME_DIR/boltrig-phenotype.json` | emotion publisher thread | desktop familiar, `/v1/familiar/phenotype` | `{v, ts, phenotype{...}}` | 5 s |
| `$XDG_RUNTIME_DIR/boltrig-express.json` | `familiar.express` handler only | desktop familiar | `{v, gesture, intensity, ttl_s}` | 5 s |
| `$XDG_STATE_HOME/boltrig/emotion-state.json` | emotion publisher thread every 20th tick | relay construction only | `{v, tenants{tid: snapshot}}` | none |
| `~/.config/familiar/genotype.json` | operator | desktop familiar | 32 named genes | none |
| camera knowledge cache (unwired) | `CameraKnowledgeCache` | itself | `{schema_version, cameras, bindings}` | none |

The state file is read exactly once, at construction, before any traffic
([`boltrig/emotion/relay.py:84`](../../../boltrig/emotion/relay.py)
`"The one construction-time read: tenant snapshots persisted by a prior process."`).

**Retention.** Nothing in this area implements a retention sweep. The retention
setting is served to the host and honoured there
([`boltrig/kernel/sensing_policy.py:263`](../../../boltrig/kernel/sensing_policy.py)
`""retention_hours": camera["retention_hours"],"`). No frames, images or
audio are stored by the kernel at any point in this area.

**Encryption.** No field here is encrypted at rest. Secrets are stored as sha256
digests only: `authorization_code_hash`, `session_token_hash`,
`claim_token_hash`, and the enrolment `digest`.

---

## 7. Configuration surface

| Variable | Default | Read at | What breaks if wrong |
| --- | --- | --- | --- |
| `BOLTRIG_DEVICE_LEASE_SIGNING_KEY` | unset | [`boltrig/kernel/device_crypto.py:97`](../../../boltrig/kernel/device_crypto.py) `"os.environ.get("BOLTRIG_DEVICE_LEASE_SIGNING_KEY", "")"` | unset means NO device or camera verbs are registered and every enrollment route answers 503. Rotating it invalidates every enrolled device's `lease_verify_key_id`, which makes issuance answer `device_verifier_stale` |
| `BOLTRIG_DEVICE_VERIFICATION_URI` | `/#/settings` | [`boltrig/kernel/device_routes.py:101`](../../../boltrig/kernel/device_routes.py) `"BOLTRIG_DEVICE_VERIFICATION_URI", "/#/settings""` | the enrollment response points a user at the wrong page |
| `BOLTRIG_DESKTOP_HANDS` | unset (off) | [`boltrig/api/bootstrap.py:137`](../../../boltrig/api/bootstrap.py) `"is_truthy(os.environ.get("BOLTRIG_DESKTOP_HANDS"))"` | off means no `desktop.*` verbs, no registry, and `/v1/hands/*` answers 503 |
| `BOLTRIG_EMOTION` | unset (orbctl heuristic) | [`boltrig/emotion/relay.py:353`](../../../boltrig/emotion/relay.py) `"flag = os.environ.get(\"BOLTRIG_EMOTION\", \"\").strip()"` | `0` forces the plain relay; on the manifest boot path `=1` is ALSO what registers `familiar.express` ([`boltrig/api/bootstrap.py:289`](../../../boltrig/api/bootstrap.py) `"if os.environ.get("BOLTRIG_EMOTION", "").strip() == "1":"`) |
| `BOLTRIG_EMOTION_TEMPO` | model value 60.0 | [`boltrig/emotion/tables.py:28`](../../../boltrig/emotion/tables.py) `"_TEMPO_ENV = "BOLTRIG_EMOTION_TEMPO""` | a non-positive or unparseable value is ignored, not fatal |
| `XDG_RUNTIME_DIR` | unset | relay, express adapter, phenotype route | unset means no phenotype file, no express delivery, and the route always answers resting |
| `XDG_STATE_HOME` | `~/.local/state` | [`boltrig/emotion/relay.py:376`](../../../boltrig/emotion/relay.py) `"state_home = os.environ.get("XDG_STATE_HOME""` | wrong path silently loses the bond across restarts |
| `BOLTRIG_EMOTION_RUNTIME_DIR` / `BOLTRIG_EMOTION_STATE_DIR` | `./.local-state/...` | [`docker-compose.vm.yml:89`](../../../docker-compose.vm.yml) `"${BOLTRIG_EMOTION_RUNTIME_DIR:-./.local-state/boltrig-runtime}"` | mis-mount means the desktop reader sees nothing |
| `BOLTRIG_ADDONS` | unset (`()`) | [`boltrig/addons/__init__.py:40`](../../../boltrig/addons/__init__.py) `"ENV_VAR = "BOLTRIG_ADDONS""` | an unregistered name RAISES at import; unset means the product presents as Boltrig and ships no Opbox harness |
| `BOLTRIG_OBO_ADAPTER_ID` | unset | [`boltrig/addons/__init__.py:248`](../../../boltrig/addons/__init__.py) `"override = os.environ.get("BOLTRIG_OBO_ADAPTER_ID")"` | wrong value seals a chat turn's bearer for the wrong adapter |
| `FAMILIAR_FPS` | 30 (10..120) | [`familiar/main.c:1358`](../../../familiar/main.c) `"const char *fps_env = getenv("FAMILIAR_FPS");"` | 60 fps roughly doubles GPU load per second |
| `FAMILIAR_SCALE` | 1.25 (0.30..2.0) | [`familiar/main.c:1365`](../../../familiar/main.c) `"const char *scale_env = getenv("FAMILIAR_SCALE");"` | 2.0 costs about 14 ms/frame at 1080p on a 680M |
| `FAMILIAR_PRESENCE_TAU` / `_IN_TAU` | 0.28 / 0.80 | [`familiar/main.c:1420`](../../../familiar/main.c) `"if ((e = getenv("FAMILIAR_PRESENCE_TAU")))"` | the entrance/exit animation timing |
| `FAMILIAR_PHENO` | on | [`familiar/main.c:1107`](../../../familiar/main.c) `"const char *pe = getenv("FAMILIAR_PHENO");"` | `0` pins the resting baseline, for a demo with no boltrig |
| `FAMILIAR_EXPRESS` | on | [`familiar/main.c:1158`](../../../familiar/main.c) `"const char *e = getenv("FAMILIAR_EXPRESS");"` | `0` ignores voluntary gestures |
| `FAMILIAR_SHADER`, `FAMILIAR_GENOTYPE`, `FAMILIAR_AUDIO_CMD`, `FAMILIAR_BAR_NS`, `FAMILIAR_BEAD_X/Y/PX` | see README | [`familiar/README.md:137`](../../../familiar/README.md) `"`FAMILIAR_FPS` (10..120, default 30)"` | shader path, identity, audio tap, dock geometry |
| `FAMILIAR_UPSTREAM_DIR` | `$HOME/Projects/beelink-desktop/familiar` | [`scripts/check_familiar_shader.sh:19`](../../../scripts/check_familiar_shader.sh) `"UPSTREAM_DIR="${FAMILIAR_UPSTREAM_DIR:-$HOME/Projects/beelink-desktop/familiar}""` | absent upstream makes the drift check exit 2 NOT CHECKED |
| `BENCH_U`, `BENCH_PPM`, `BENCH_WORLD`, `BENCH_ORIGIN`, `BENCH_FILL`, `BENCH_PRESENCE`, `BENCH_GENE` | unset | [`familiar/README.md:125`](../../../familiar/README.md) `"BENCH_U="uIrritation=0.9""` | headless bench sweeps and geometry verification |

Manifest keys: none. This area is configured entirely by environment and by
per-user settings rows. That is the shape decision 0035 asks for
([`docs/decisions/0035-presence-equals-provisioning.md:35`](../../../docs/decisions/0035-presence-equals-provisioning.md)
`"No new build-time flags for deployment shape."`), with the two exceptions
`BOLTRIG_EMOTION` and `BOLTRIG_DESKTOP_HANDS`, which remain runtime env switches
rather than provisioning facts.

---

## 8. PROCESS

### 8.1 Bringing sensing up on a live stack

`scripts/activate-sensing.sh` (1,140 lines) and
[`docs/ACTIVATE-SENSING-RUNBOOK.md`](../../../docs/ACTIVATE-SENSING-RUNBOOK.md)
are the procedure. Dry run is the DEFAULT; `--apply` additionally demands a typed
confirmation per mutating step
([`docs/ACTIVATE-SENSING-RUNBOOK.md:61`](../../../docs/ACTIVATE-SENSING-RUNBOOK.md)
`"Dry run is the default. Without `--apply` the script changes nothing."`).

Ordered steps and why the order is load bearing:

    key  ->  1-migrate  ->  2-deploy  ->  3-enrol  ->  4-bind  ->  5-enable  ->  6-verify

- `key` before `2-deploy`, because `env_file` is read when the container is
  CREATED, so adding the key afterwards needs a second recreate.
- `1-migrate` before `2-deploy`, because readiness compares alembic heads with
  strict equality and a new image on an old schema stacks a second failure that
  cannot be told apart from the pre-existing one.
- `4-bind` before `5-enable`, because `PUT /v1/me/sensing/camera` re-checks the
  binding against `camera_bindings` and answers 409 for a camera nobody
  published ([`docs/ACTIVATE-SENSING-RUNBOOK.md:104`](../../../docs/ACTIVATE-SENSING-RUNBOOK.md)
  `"**`4-bind` before `5-enable`.**"`).

The postconditions are chosen to DISCRIMINATE rather than to look green. The
clearest single signal is `GET .../sensing-config` answering 401 rather than 404:
404 means the old image is still serving, 401 means the route is live and
refusing an unauthenticated caller
([`docs/ACTIVATE-SENSING-RUNBOOK.md:131`](../../../docs/ACTIVATE-SENSING-RUNBOOK.md)
`"404 = the old image is still serving; 401 = the route is live"`).
Container health is explicitly NOT a postcondition, because `model_gateway` is a
required readiness probe that was already failing.

Rollbacks are per step. Two are worth restating: `compose build` retags
`boltrig/kernel:0.1.0` and the running image has no other tag, so the script
tags the running image `boltrig/kernel:rollback-<stamp>` BEFORE building and that
retag IS the rollback; and there is no delete route for `camera_bindings`, so the
withdrawal that counts is clearing the settings binding
([`docs/ACTIVATE-SENSING-RUNBOOK.md:152`](../../../docs/ACTIVATE-SENSING-RUNBOOK.md)
`"**There is no delete route for `camera_bindings`.**"`).

### 8.2 Keeping a device session alive, and what cannot be recovered

`SESSION_TTL` is 24 hours, enforced in SQL by
`session_expires_at >= now()`. Renewal is PREVENTION, not repair: `rotate_session`
authenticates first, so there is no path from a lapsed token back to a live one,
and the only re-issuance path demands `actor_tier == "human"`. The host therefore
renews at the halfway mark, buying a 12 hour kernel-outage budget
([`docs/ACTIVATE-SENSING-RUNBOOK.md:240`](../../../docs/ACTIVATE-SENSING-RUNBOOK.md)
`"**RENEWAL IS PREVENTION, NOT REPAIR"`). Revocation is absolute: `revoke_device`
NULLs both session columns, so every later rotate is a 401 forever
([`boltrig/store/device_pg.py:107`](../../../boltrig/store/device_pg.py)
`"UPDATE devices SET revoked_at=now(),presence='revoked',"`).

Three host daemons share one credential under a non-blocking `flock`, so one
rotates per window and the others adopt the new token on their next poll. The
measured cost of a concurrent rotation is one skipped poll, not a stand-down.

The Tauri agent's own recovery: an `Unauthorized` on any call invalidates the
stored agent and emits a status
([`apps/worker/src-tauri/src/device_agent.rs:303`](../../../apps/worker/src-tauri/src/device_agent.rs)
`"invalidate_agent(app, runtime, "device_session_rejected")?;"`), and it rotates
proactively 15 minutes before expiry
([`apps/worker/src-tauri/src/device_agent.rs:30`](../../../apps/worker/src-tauri/src/device_agent.rs)
`"const ROTATE_WITHIN_SECONDS: i64 = 15 * 60;"`).

### 8.3 Changing the Familiar's look

- **Never edit `familiar.frag` in `apps/worker`.** The vendored copy must stay
  byte-identical to `familiar/familiar.frag`, checked by
  [`apps/worker/tests/familiarShaderParity.test.ts:17`](../../../apps/worker/tests/familiarShaderParity.test.ts)
  `"worker's vendored familiar.frag is byte-identical to the canon"`. Both files
  hash to `aca897f206388b84ac93cbf8debb1181d8c3fda5e54939a487be65b8dde70035`,
  which the bundle manifest also pins
  ([`apps/worker/src/bundles/familiar/character.json:13`](../../../apps/worker/src/bundles/familiar/character.json)
  `""sha256": "aca897f206388b84ac93cbf8debb1181d8c3fda5e54939a487be65b8dde70035""`).
- **The second drift check reaches outside the repo.**
  `scripts/check_familiar_shader.sh` compares against
  `$HOME/Projects/beelink-desktop/familiar/familiar.frag` and exits 2 with
  `NOT CHECKED` rather than reporting an agreement it did not observe
  ([`scripts/check_familiar_shader.sh:37`](../../../scripts/check_familiar_shader.sh)
  `"echo "NOT CHECKED: no upstream $f at $upstream" >&2"`).
- **Tune the host, not the GLSL.** The 24 dials in `familiarTuning.ts` and the
  per-mode deltas in `familiarPresets.ts` are what a person changes, and the
  bench drives the shipped renderer through `setTuning`
  ([`docs/decisions/0030-familiar-modes-and-dials.md:65`](../../../docs/decisions/0030-familiar-modes-and-dials.md)
  `"**The bench drives the real renderer.**"`).
- **Measure the desktop shader headlessly.** `make bench && ./build/familiar-bench
  familiar.frag 1920 1080 40` prints ms/frame plus a sanity readback so a black
  rectangle cannot ship ([`familiar/README.md:114`](../../../familiar/README.md)
  `"make bench && ./build/familiar-bench familiar.frag 1920 1080 40"`).
  `familiar-bench` is surfaceless: never create a headless wayland output on that
  box, because lan-mouse rebinds its edge capture to it and the cursor is
  swallowed invisibly ([`familiar/README.md:159`](../../../familiar/README.md)
  `"**Never create headless outputs on this box**"`).
- **`make install` runs `check.sh` and a violating build is not installable**
  ([`familiar/Makefile:49`](../../../familiar/Makefile)
  `"install: all check"`). `check.sh` binds WL-1 and WL-2 with static greps plus a
  live `hyprctl layers` intersection test against the KVM capture strip.
- **Swap the room live** with `use-realm N`, which rewrites the `#define
  FAMILIAR_REALM` in the installed shader and sends SIGUSR1, keeping the old
  program if the new one fails to compile
  ([`familiar/README.md:81`](../../../familiar/README.md)
  `"Swap live with `use-realm N`"`).
- **Fire a gesture by hand** with `fire-gesture <name>`, installed alongside
  ([`familiar/Makefile:51`](../../../familiar/Makefile)
  `"install -Dm755 fire-gesture.sh $(PREFIX)/bin/fire-gesture"`).
- **Hot reload** the installed shader with
  `systemctl --user kill -s USR1 familiar`.

### 8.4 iOS island

`make familiar-island` builds the island page and copies it into the iOS bundle;
`make familiar-island-check` refuses a committed page that `apps/worker/src` no
longer builds, and `worker-quality` runs that check
([`Makefile:246`](../../../Makefile)
`"$(MAKE) --no-print-directory familiar-island-check"`).

### 8.5 Turning the emotion add-on on in a container

`orbctl` does not exist in a container, so the desktop heuristic would leave the
relay off; the VM compose sets `BOLTRIG_EMOTION: "1"` and bind-mounts both paths
to the host ([`docker-compose.vm.yml:82`](../../../docker-compose.vm.yml)
`"BOLTRIG_EMOTION: "1""`). Only the boltrig state directory is mounted, not all
of `~/.local/state`, because the relay resolves
`$XDG_STATE_HOME/boltrig/emotion-state.json`.

### 8.6 Diagnosing "the camera sees nothing"

In order, because each hides the next:

1. Is a lease signing key set? Without it every device route answers 503 before
   looking at anything else, and no `camera.*` verb is registered at all.
2. Is the deployed image newer than the `sensing-config` route? `GET` it: 404
   means the image predates it.
3. Is there a device row and a live session? A half-written credential file
   passes the shape check and is then rejected as `invalid_device_session`, so
   the host LOOKS provisioned.
4. Is there a `camera_bindings` row? No binding reads as `camera_not_bound`.
5. Has the camera moved USB port? The identity changes, the binding stops
   matching, and nothing about the camera changed. Re-bind rather than debug.
6. Is the user setting on? `DEFAULT_CAMERA_ENABLED` is False, so a fresh Boltrig
   watches nothing.

---

## 9. Failure modes and fail-open/fail-closed posture

| Guard | Direction | Proof |
| --- | --- | --- |
| No lease signing key | FAIL CLOSED | 503 before any state read: [`boltrig/device_leases.py:51`](../../../boltrig/device_leases.py) `"raise DeviceLeaseIssueError("device_leases_unavailable", 503)"`; verbs are not even registered ([`boltrig/api/device_bootstrap.py:18`](../../../boltrig/api/device_bootstrap.py) `"log.info("device action verbs disabled"`) |
| Stale device verifier | FAIL CLOSED | 409 `device_verifier_stale` when the device's recorded key id is not this signer's |
| Approval evidence | FAIL CLOSED | nine ANDed clauses, one 403 reason, plus an independent SQL re-check on insert |
| Self approval | FAIL CLOSED | respondent may not be the requester or the on-behalf subject: [`boltrig/camera_leases.py:203`](../../../boltrig/camera_leases.py) `"response.respondent in {request.requested_by"` |
| Run cancelled | FAIL CLOSED | checked at context, at materialize, and in the pending-lease query |
| Camera not proven | FAIL CLOSED | `camera.ptz.set` requires `ptz_set_state == "proven"` in Python, in the memory store and in SQL |
| Claim race | FAIL CLOSED | compare-and-set on `status='issued'` plus the exact signature; a second claim gets 409 |
| Settle race | FAIL CLOSED | requires `status='claimed'`, a matching claim-token digest and a live claim expiry |
| Receipt size | FAIL CLOSED | 32,000 byte cap, rejected not truncated |
| Camera evidence size | FAIL CLOSED | 64,000 bytes / 64 entries, rejected not truncated |
| Validation reason leakage | FAIL CLOSED | allow-listed reason codes; anything else becomes `invalid_request` |
| Sensing consent parse | FAIL CLOSED (toward off) | [`boltrig/kernel/sensing_policy.py:15`](../../../boltrig/kernel/sensing_policy.py) `"EVERY PARSE FAILS TOWARD OFF."` A binding that will not parse is no binding |
| Presence without a threshold | FAIL CLOSED | 409 at the toggle, and `sensing_config` reports `enabled: false` regardless of the stored value |
| Unknown sensing capability | FAIL CLOSED | `capability_unknown`, with no remedy pointer, because pointing at Settings would send the user looking for a control that cannot exist |
| Kernel unreachable, Worker side | FAIL CLOSED, and HONESTLY | its own reason code `kernel_unreachable` rather than `camera_disabled`: [`apps/worker/src/components/StageBody.tsx:118`](../../../apps/worker/src/components/StageBody.tsx) `"const unreachable = (capability: string): SensingDecision"` |
| Desktop hands, add-on off | FAIL CLOSED | no adapter, no verbs, 503 `hands_unavailable` |
| Hands command expiry | FAIL CLOSED | 30 s TTL swept lazily; a swept command wakes its waiter with no receipt, which resolves as a timeout |
| Hands receipt for an unknown id | FAIL CLOSED and UNAUDITED | 404 and deliberately no audit row, so a no-op is never recorded as an execution |
| Native camera lease verification | FAIL CLOSED, TWICE | the kernel signs, the device re-verifies envelope, digest and signature, and then re-checks the live descriptor |
| Emotion relay | FAIL OPEN, by design (P9) | every exception in `publish`, in the publisher thread, in table loading and in the factory is swallowed: [`boltrig/emotion/relay.py:106`](../../../boltrig/emotion/relay.py) `"except Exception:  # noqa: BLE001 - cosmetic channel, never let it touch a run"` |
| Emotion snapshot restore | FAIL OPEN, toward a fresh engine | every field falls back independently: [`boltrig/emotion/engine.py:270`](../../../boltrig/emotion/engine.py) `"corrupt state file must degrade to a fresh engine, never raise, P9"` |
| Phenotype projection | FAIL OPEN, toward RESTING | every failure answers the resting shape, never an error, so a client cannot learn to treat absence as a fault |
| `familiar.express` delivery | FAIL OPEN, best effort | the governed act is the dispatch; `delivered: false` is the honest report |
| Desktop familiar, no compositor or GPU or phenotype | FAIL OPEN, typed | WL-2: a typed message on stderr or the resting baseline, never a crash ([`familiar/check.sh:19`](../../../familiar/check.sh) `"WL-2: no compositor / no GPU / no phenotype degrades typed, never crashes"`) |
| Stage renderer failure | FAIL OPEN, toward the badge | never rewrite the look to survive a failure |
| Addon name typo | FAIL CLOSED, LOUDLY | `active_addons()` raises at import rather than shipping a boltrig with no integration seam |
| Addon entry-point name collision | FAIL CLOSED | refuses rather than letting a squatter inherit the adapter claim |
| Missing on-behalf adapter | FAIL CLOSED to the NARROWER choice | failing to seal would use the adapter's static service credential, which is WIDER, so a single registered claim is used as a fallback: [`boltrig/addons/__init__.py:256`](../../../boltrig/addons/__init__.py) `"Fall back to what this BUILD ships"` |

**The asymmetry is deliberate and consistent.** Anything that ACTS fails closed.
Anything that only EXPRESSES fails toward a calm resting state, because a
cosmetic side-channel that raises teaches every client to treat its absence as a
fault ([`boltrig/kernel/sensing_capability.py:8`](../../../boltrig/kernel/sensing_capability.py)
`"Contrast ``familiar_phenotype_routes``, which answers *resting*"`). Sensing is
the one case that deliberately sits on the acting side even though it produces
no action: absent capability must be VISIBLE, so it returns an explicit refusal
object.

---

## 10. What is proven

| Invariant | Binds | Named tests |
| --- | --- | --- |
| `SEC-WRK-07` | the whole device lease lifecycle: enrollment, digest-only rotatable sessions, bounded verbs, exact non-self approval, single materialization, cancel/revoke, atomic claim fencing | 8 nodes in `tests/security/test_device_dispatch_adapter.py`, 6 in `tests/security/test_device_leases.py`, `tests/store/test_device_store_parity.py::test_device_lifecycle_and_lease_cas_match_on_both_stores` ([`tests/invariants.yaml:2456`](../../../tests/invariants.yaml) `"SEC-WRK-07:"`) |
| `SEC-WRK-10` | the Familiar genotype is a deterministic identity-only projection of `AgentCapability.name`, with no runtime or authority state | `tests/unit/test_familiar_identity.py::test_agent_capability_name_derives_one_pinned_versioned_genotype`, `::test_genotype_projection_contains_no_authority_or_runtime_state` |
| `EMO-1` | emotion is downstream of dispatch; outcomes identical with and without the relay; no kernel module imports the package | `tests/emotion/test_relay.py::test_dispatch_outcomes_are_identical_with_and_without_the_emotion_relay`, `::test_no_kernel_module_imports_the_emotion_package` |
| `EMO-2` | no message content reaches snapshots or the phenotype file | `tests/emotion/test_relay.py::test_message_content_never_reaches_snapshots_or_the_phenotype_file` |
| `EMO-3` | `appraise()` is pure, enforced by determinism plus an AST import whitelist | `tests/emotion/test_engine.py::test_appraise_is_deterministic_for_identical_inputs`, `::test_engine_module_imports_stay_inside_the_pure_whitelist` |
| `EMO-4` | engines are per tenant | `tests/emotion/test_relay.py::test_tenant_b_events_leave_tenant_a_engine_untouched` |
| `EMO-5` | the appraisal table is data | `tests/emotion/test_engine.py::test_appraisal_table_is_data_and_mutating_it_changes_behavior` |
| `EMO-6` | attachment accumulates only from appraisals, decays in real days, lifts baselines only, survives the snapshot round trip | `tests/emotion/test_engine.py::test_attachment_decays_in_real_days_never_tempo_scaled`, `::test_attachment_zero_is_the_0013_engine_verbatim` |
| `EMO-7` | the Worker phenotype projection is whitelisted, clamped, content free, importing nothing from the emotion package, resting on every failure | 3 nodes in `tests/emotion/test_phenotype_projection.py` |
| `P9` | the emotion channel never raises out of `publish` | `tests/emotion/test_relay.py::test_a_broken_engine_or_unwritable_path_never_raises_out_of_publish` |
| `WL-3` | `familiar.express` is registered with a binding, denied and audited when ungranted, schema-rejected on a bad gesture, and writes nothing in either failure case | 4 nodes in `tests/security/test_familiar_express.py` |
| `DH-1` | desktop control goes through the chokepoint with no side door | 7 nodes in `tests/security/test_desktop_hands.py`, plus `::test_desktop_verbs_only_exist_when_the_addon_is_enabled` |
| `SEC-WRK-26` | the addon inventory is a read-only, scoped, secret-free projection | 3 nodes in `tests/security/test_addon_inventory.py` |

**Unbound but tested.** These have real tests and NO invariant id:

- Camera leases and the camera transport: `tests/camera/test_camera_leases.py`
  (3 nodes), `tests/camera/test_camera_transport.py` (3 nodes),
  `tests/camera/test_camera_adapter.py` (3 nodes),
  `tests/camera/test_discovery.py` (11 nodes). Bounded search:
  `grep -n -i "camera" tests/invariants.yaml`, 2026-08-24, returns exactly one
  line, and it is about the browser CSP.
- Sensing consent: `tests/security/test_sensing_settings.py` (11 nodes).
  Bounded search: `grep -n -i "sensing" tests/invariants.yaml` returns nothing.
- The emotion affordances: `tests/emotion/test_affordances.py` (3 nodes) and
  `tests/test_familiar_emotion_routes.py` (2 nodes), neither referenced by any
  `EMO-*` entry.
- The Familiar Stage and shader parity: `apps/worker/tests/familiarStage.test.tsx`,
  `familiarShaderParity.test.ts`, `familiarDrive.test.ts`, `familiarBundle.test.ts`,
  `familiarIsland.test.ts`, `phenotypeContract.test.ts`,
  `sdks/web/tests/familiar-state-contracts.test.ts`.

**Named but NOT covered by any test node.** Fourteen requirements below carry
`IMPLEMENTED-UNTESTED` with their search bound stated inline. The recurring gaps
are: the `human_required` tier guard on every owner-facing device and camera
route (bounded: `rg -n "human_required" tests/`, 2026-08-24, no hits, and every
device-lease test sends `x-boltrig-tier: human`); the camera physical-proof
evidence clause; the atomic-write shape and the twentieth-tick state snapshot in
the emotion publisher; and the whole native half of the camera plane, which is
Rust and Objective-C and is exercised only by the two `#[cfg(test)]` functions in
`camera_protocol.rs`.

**WL-1 and WL-2 are bound by a shell script, not a test node.**
[`familiar/check.sh`](../../../familiar/check.sh) is run by `make install`
([`familiar/Makefile:49`](../../../familiar/Makefile) `"install: all check"`), so
a violating build cannot be installed on the box that runs it. It does not run in
this repository's Python or Worker suites.

**Cross-language agreement is pinned by a fixture, not by prose.** The Rust
verifier carries the Python digest for one exact camera action:
[`apps/worker/src-tauri/src/camera_protocol.rs:298`](../../../apps/worker/src-tauri/src/camera_protocol.rs)
`"fn rust_matches_python_camera_action_digest_fixture"`, asserting
`9aaeb146f7b4c30da06150636f4a092e3b6b7dfbb10a0537b1e72d48ff8ae83b`.

---

## 11. RISKS

RISK: `GET /v1/familiar/phenotype` claims to be owner-scoped but ignores the
principal entirely and returns a PROCESS-WIDE file, so any authenticated
principal of any tenant reads whichever tenant's mood the publisher last wrote.
[`boltrig/kernel/familiar_phenotype_routes.py:82`](../../../boltrig/kernel/familiar_phenotype_routes.py)
`"async def familiar_phenotype(p=principal):"` with `p` unused, against the
docstring at line 83 `"Owner-scoped, cosmetic, read-only"`. EMO-4 scopes the
ENGINES, not the published file.

RISK: the emotion publisher only ever publishes ONE tenant's phenotype, chosen as
the engine named `"default"` or, failing that, the single engine when exactly one
exists. A two-tenant process where neither is `"default"` publishes nothing at
all, silently. [`boltrig/emotion/relay.py:303`](../../../boltrig/emotion/relay.py)
`"engine = self._engines.get(self._tenant)"`.

RISK: no invariant in `tests/invariants.yaml` binds the camera lease plane or the
sensing consent surface, although both are security-relevant and both carry a
consumed-approval and a consent gate. The camera plane is the exact shape
`SEC-WRK-07` binds for devices. Bounded: `grep -n -i "camera\|sensing" tests/invariants.yaml`,
2026-08-24, one hit, about CSP.

RISK: `camera.ptz.get` and `camera.ptz.set` are declared
`idempotency_mode: "cacheable"` ([`boltrig/adapters/builtin/camera_leases.py:32`](../../../boltrig/adapters/builtin/camera_leases.py)
`""idempotency_mode": "cacheable","`), while decision 0016's stated reasoning
for the sibling desktop verbs is that a replayed receipt claiming a delivery that
did not happen is unacceptable for anything that changes host state
([`docs/decisions/0016-desktop-hands.md:56`](../../../docs/decisions/0016-desktop-hands.md)
`"Idempotency reasoning: `cacheable` means a retry"`). A cached `camera.ptz.set`
result returns a lease id whose lease may already be settled or expired.

RISK: the shipped `descriptor_fingerprint` is a hash of USB TOPOLOGY
(`vid:pid:bus:port.path`), not of the descriptor
([`apps/worker/src-tauri/src/camera_uvc.m:202`](../../../apps/worker/src-tauri/src/camera_uvc.m)
`""%04x:%04x:%u:", vendor, product,"`). The field name asserts a property the
value does not have: it changes when the camera is replugged elsewhere and does
NOT change when the device's descriptors change. `boltrig/camera/discovery.py`
computes the descriptor-shaped one, and that module is unwired.

RISK: `boltrig/camera/` (7 modules, 1165 lines) and
`boltrig/adapters/builtin/camera.py` (128 lines, four verbs including
`camera.snapshot`) are reachable only from tests. Two classes named
`id = "camera"` exist; registering both on one tenant would collide. Bounded
search stated in section 4.4.

RISK: `docs/DESIGN-familiar-in-boltrig.md` describes a genotype derived from a
ROLE (orchestrator, researcher, reviewer, builder, guardian, analyst) rendered
through `ui/src/panels/chat/AgentAvatar.tsx`. Neither exists: the shipped
derivation is a sha256 over the capability name selecting one of four astronomy
bodies ([`boltrig/models/familiar.py:62`](../../../boltrig/models/familiar.py)
`"body=_BODIES[digest[0] % len(_BODIES)],"`), and there is no `ui/` directory in
the pinned tree. The document carries no status header saying it is superseded.

RISK: `presence = 'locked'` is a legal value of the `devices` CHECK constraint
and of the SDK's `DevicePresence` union, and nothing in the tree ever writes it.
Bounded: `rg -n "'locked'|\"locked\"" boltrig/ apps/worker/src-tauri/src/ sdks/ tests/`,
2026-08-24, hits only the enum declarations. `offline` is likewise write-once at
creation and never restored. A UI reading `presence` cannot distinguish a device
that has gone away from one that is online.

RISK: `availability_mode` is projected to owners and rendered in the Worker
device list, yet its CHECK admits exactly one value
([`migrations/versions/0042_desktop_devices.py:40`](../../../migrations/versions/0042_desktop_devices.py)
`"CHECK (availability_mode IN ('unlocked_session'))"`). It is a field that cannot
carry information.

RISK: the hands registry is kernel-global rather than tenant scoped, so on a
multi-tenant deployment any authenticated principal polling `/v1/hands/commands`
claims commands queued by any tenant. Decision 0016 records this as a known
limit ([`docs/decisions/0016-desktop-hands.md:74`](../../../docs/decisions/0016-desktop-hands.md)
`"The registry is kernel-global, not tenant-scoped"`), and
[`boltrig/kernel/desktop_routes.py:61`](../../../boltrig/kernel/desktop_routes.py)
`"for cmd in reg.pending():"` confirms no tenant filter.

RISK: `GET /v1/sensing/capability` cannot enforce declaration and the module says
so at length, but the route is what a client naturally reads as the enforcement
point. The Stage constraint that limits asks to `wantsSensing` is not a boundary,
because a character add-in shares the Worker's JavaScript realm and can call
`client.sensingCapability` for anything
([`boltrig/kernel/sensing_capability.py:35`](../../../boltrig/kernel/sensing_capability.py)
`"the Stage and NOT a security boundary"`).

RISK: `signer_for` falls back to reading the environment on EVERY request when
`app.state.device_lease_signer` is unset
([`boltrig/kernel/device_route_support.py:28`](../../../boltrig/kernel/device_route_support.py)
`"DeviceLeaseSigner.from_environment()"`, reached by the `or` on the line above),
so an env change mid-process
silently changes the signing identity between two requests of one flow.

RISK: `boltrig/api/bootstrap.py` registers `familiar.express` unconditionally on
the demo seed path ([`boltrig/api/bootstrap.py:119`](../../../boltrig/api/bootstrap.py)
`"build_familiar())  # familiar.express (WL-3)"`) but only when
`BOLTRIG_EMOTION == "1"` on the manifest path (line 289). The two boot paths
disagree about whether the verb exists, and neither is gated on the express
channel actually being readable.

RISK: `scripts/check_familiar_shader.sh` compares the vendored copy against a
path outside the repository, while an identical canonical copy now exists inside
it at `familiar/familiar.frag`. The in-repo vitest covers that pair; the shell
script's external comparison exits 2 on the machines that lack the checkout, so
its green is unavailable in CI by construction.

RISK: `camera_bindings` rows have no delete route and no expiry. The runbook
records this as an accepted orphan
([`docs/ACTIVATE-SENSING-RUNBOOK.md:152`](../../../docs/ACTIVATE-SENSING-RUNBOOK.md)
`"The row stays, orphaned and inert"`), which means a revoked device's bindings
persist until the CASCADE fires on the `devices` row.

RISK: `libraries/emotion/event_map.yaml` carries the same two-line comment about
adoption twice, once at lines 34 to 35 and again at 37 to 38, with the rule
itself only after the second copy. It is cosmetic, but it is the shape of a bad
merge in a data file that changes runtime behaviour with no code review gate.

## 12. OPEN QUESTIONS

1. **"The membrane" does not name any Familiar concept in this tree.** Bounded:
   `rg -ni "membrane"` over the pinned tree, 2026-08-24, returns zero hits in
   `familiar/`, in `familiar.frag` (either copy) and in `boltrig/`. Every hit is
   Ultron's body ([`apps/worker/src/components/ultron/shadersUltron.ts:1`](../../../apps/worker/src/components/ultron/shadersUltron.ts)
   `"Ultron's body: a fracturing membrane, not an instrument."`) or Jarvis's
   lattice. What would settle it: whether the brief meant Ultron's membrane, or a
   term used outside the repository.
2. **Does anything produce `FamiliarStateV2`?** The contract, its sanitizer and
   its unit tests exist; no producer or consumer does. Decision 0025 calls it a
   follow-up that "belongs in the web SDK". Settled by finding a producer in
   another repository or by a decision retiring the contract.
3. **Is the `boltrig/camera/` discovery package intended to be wired, retired, or
   kept as the reference model for a future platform layer?** It has a complete
   `CameraBackend` protocol with 18 methods and no implementation in this tree.
   Settled by a decision record; there is none among the 41 in `docs/decisions/`.
4. **What sets `presence` back to `offline`?** Nothing observed. Settled by a
   sweeper, a heartbeat expiry rule, or a decision to drop the column to the two
   values that are actually written.
5. **Are the sensing daemons (`camerad`, `capture_policy.py`, `presence.py`) in
   scope for this repository at all?** They are cited by path but live in
   `~/Projects/companion-observer`
   ([`docs/ACTIVATE-SENSING-RUNBOOK.md:311`](../../../docs/ACTIVATE-SENSING-RUNBOOK.md)
   `"~/Projects/companion-observer/capture_policy.py"`), so every claim about
   their behaviour here is a claim about a SEAM. Settled by vendoring them or by
   an explicit statement that they are a separate product.
6. **Does the Unreal premium backend exist anywhere?** Decision 0025 names
   `boltrig-familiar` `unreal/FamiliarUE/` and pins the editor MCP to loopback
   port 8765 ([`docs/decisions/0025-familiar-stage-renderer-ladder.md:68`](../../../docs/decisions/0025-familiar-stage-renderer-ladder.md)
   `"MCP binds 127.0.0.1:8765 (8000 is Boltrig's)"`). Nothing in this tree
   references it (bounded: grep -rni unreal over apps/ boltrig/ sdks/ familiar/
   for .ts, .tsx, .py and .rs, 2026-08-24, one hit, a forward-looking comment). Settled by a checkout of
   that repository.
7. **What re-issues a device session after a 24 hour lapse without a human?**
   By construction nothing can, and the runbook states that plainly. Whether that
   is the intended permanent posture for an unattended host, or a gap awaiting a
   machine re-enrolment path, is a product decision that is not recorded.

## 13. Requirements

| id | statement | status | evidence | invariant |
| --- | --- | --- | --- | --- |
| BT-REQ-1400 | Device enrollment start refuses any actor whose tier is not human. | IMPLEMENTED-UNTESTED | [`boltrig/kernel/device_routes.py:72`](../../../boltrig/kernel/device_routes.py) `"return _error(\"human_required\", 403)"` (no test asserts the non-human refusal; bounded: rg -n human_required tests/, 2026-08-24, no hits) | SEC-WRK-07 |
| BT-REQ-1401 | An enrollment authorization code is an opaque scoped token whose sha256 alone is stored, expiring after ten minutes. | IMPLEMENTED | [`boltrig/kernel/device_routes.py:88`](../../../boltrig/kernel/device_routes.py) `"authorization_code_hash=token_digest(code),"` | SEC-WRK-07 |
| BT-REQ-1402 | Completing enrollment consumes the code atomically and returns a session token plus the Ed25519 lease verifier. | IMPLEMENTED | [`boltrig/kernel/device_agent_routes.py:60`](../../../boltrig/kernel/device_agent_routes.py) `"completed = await kernel.store.complete_device_enrollment("` | SEC-WRK-07 |
| BT-REQ-1403 | A device session bearer is validated by scoped-token kind, device id equality and stored digest, and expires after 24 hours. | IMPLEMENTED | [`boltrig/kernel/device_route_support.py:43`](../../../boltrig/kernel/device_route_support.py) `"parse_scoped_token(token, \"device_session\")"` | SEC-WRK-07 |
| BT-REQ-1404 | Session rotation authenticates the live session first, so a lapsed token can never be exchanged for a live one. | IMPLEMENTED | [`boltrig/kernel/device_agent_routes.py:169`](../../../boltrig/kernel/device_agent_routes.py) `"device = await authenticate_device(request, kernel, device_id)"` | SEC-WRK-07 |
| BT-REQ-1405 | Revoking a device sets revoked_at, sets presence to revoked and NULLs both session columns. | IMPLEMENTED | [`boltrig/store/device_pg.py:107`](../../../boltrig/store/device_pg.py) `"UPDATE devices SET revoked_at=now(),presence='revoked',"` | SEC-WRK-07 |
| BT-REQ-1406 | A file write lease is refused on a read-only root and a command lease is refused on a root without command_enabled. | IMPLEMENTED | [`boltrig/device_leases.py:69`](../../../boltrig/device_leases.py) `"raise DeviceLeaseIssueError(\"root_is_read_only\", 403)"` | SEC-WRK-07 |
| BT-REQ-1407 | A device lease expires 120 seconds after issue. | IMPLEMENTED | [`boltrig/device_leases.py:14`](../../../boltrig/device_leases.py) `"DEVICE_LEASE_TTL = timedelta(seconds=120)"` | SEC-WRK-07 |
| BT-REQ-1408 | A device lease materializes only against a CONSUMED APPROVAL HITL request whose action digest matches and whose respondent is neither the requester nor the on-behalf subject. | IMPLEMENTED | [`boltrig/device_leases.py:135`](../../../boltrig/device_leases.py) `"\"consumed_exact_action_approval_required\", 403"` | SEC-WRK-07 |
| BT-REQ-1409 | One approval can materialize at most one device lease, enforced by a UNIQUE (tenant_id, approval_id). | IMPLEMENTED | [`migrations/versions/0042_desktop_devices.py:70`](../../../migrations/versions/0042_desktop_devices.py) `"PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,approval_id),"` | SEC-WRK-07 |
| BT-REQ-1410 | Claiming a lease requires the exact stored signature, verifies it with the kernel signer, and is a single-use compare-and-set with a five minute claim window. | IMPLEMENTED | [`boltrig/kernel/device_agent_routes.py:104`](../../../boltrig/kernel/device_agent_routes.py) `"or not signer.verify(lease)"` | SEC-WRK-07 |
| BT-REQ-1411 | Settling requires status claimed, a matching claim token digest and an unexpired claim, and accepts only completed or failed. | IMPLEMENTED | [`boltrig/store/device_pg.py:284`](../../../boltrig/store/device_pg.py) `"AND claim_token_hash=$4 AND status='claimed'"` | SEC-WRK-07 |
| BT-REQ-1412 | A settlement receipt is rejected, never truncated, above 32000 canonical bytes. | IMPLEMENTED | [`boltrig/kernel/device_agent_routes.py:152`](../../../boltrig/kernel/device_agent_routes.py) `"return _error(\"receipt_too_large\")"` | SEC-WRK-07 |
| BT-REQ-1413 | The owner-facing lease view projects only bounded, validated receipt metadata and pins command output_captured to false. | IMPLEMENTED | [`boltrig/kernel/device_route_support.py:200`](../../../boltrig/kernel/device_route_support.py) `"\"output_captured\": False,"` | SEC-WRK-07 |
| BT-REQ-1414 | Device and camera verbs are registered only when a lease signing key is present in the environment. | IMPLEMENTED | [`boltrig/api/device_bootstrap.py:18`](../../../boltrig/api/device_bootstrap.py) `"device action verbs disabled (lease signing key unavailable)"` | SEC-WRK-07 |
| BT-REQ-1415 | device.command.run accepts an argv array only; no schema field anywhere on the device lease path carries a shell string. | IMPLEMENTED | [`boltrig/models/device_actions.py:120`](../../../boltrig/models/device_actions.py) `"if set(raw) - {\"argv\", \"cwd_relative\", \"timeout_seconds\"}:"` | SEC-WRK-07 |
| BT-REQ-1416 | All four device verbs are HIGH consequence, rate limited to 30 per minute per tenant. | IMPLEMENTED | [`boltrig/adapters/builtin/device.py:109`](../../../boltrig/adapters/builtin/device.py) `"\"consequence\": \"high\","` | SEC-WRK-07 |
| BT-REQ-1417 | A camera lease expires 120 seconds after issue and the store refuses an expiry beyond that window. | IMPLEMENTED | [`boltrig/store/camera_pg.py:99`](../../../boltrig/store/camera_pg.py) `"AND $11 > now() AND $11 <= now() + interval '120 seconds'"` | - |
| BT-REQ-1418 | A camera lease carries no root, no path, no argv and no command field in its canonical payload. | IMPLEMENTED | [`tests/camera/test_camera_transport.py:101`](../../../tests/camera/test_camera_transport.py) `"assert \"root_id\" not in lease.canonical_payload()"` | - |
| BT-REQ-1419 | Camera bindings are published only over an authenticated device session and the store re-derives owner_id from the devices row. | IMPLEMENTED | [`boltrig/store/camera_pg.py:15`](../../../boltrig/store/camera_pg.py) `"SELECT $1,$2,$3,$4,d.owner_id,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14"` | - |
| BT-REQ-1420 | A binding claiming ptz_set_state proven without the bounded set-readback-restoration evidence string is refused. | IMPLEMENTED-UNTESTED | [`boltrig/kernel/camera_agent_routes.py:88`](../../../boltrig/kernel/camera_agent_routes.py) `"raise ValueError(\"camera_physical_proof_evidence_required\")"` (bounded: rg -n camera_physical_proof_evidence_required tests/, 2026-08-24, no hits) | - |
| BT-REQ-1421 | Camera lease issuance requires a connected binding, a readable or proven get state, a proven set state for camera.ptz.set, and a descriptor fingerprint equal to the action's. | IMPLEMENTED | [`boltrig/camera_leases.py:155`](../../../boltrig/camera_leases.py) `"raise CameraLeaseIssueError(\"camera_binding_not_proven\", 409)"` | - |
| BT-REQ-1422 | Camera lease materialization applies the same consumed, non-self, exact-digest approval test as the device path. | IMPLEMENTED | [`boltrig/camera_leases.py:208`](../../../boltrig/camera_leases.py) `"raise CameraLeaseIssueError(\"consumed_exact_action_approval_required\", 403)"` | - |
| BT-REQ-1423 | One approval can materialize at most one camera lease, enforced in SQL and by a UNIQUE (tenant_id, approval_id). | IMPLEMENTED | [`migrations/versions/0068_camera_uvc_leases.py:49`](../../../migrations/versions/0068_camera_uvc_leases.py) `"PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,approval_id),"` | - |
| BT-REQ-1424 | Camera lease claim and settlement use the same signature check, claim token digest and terminal status set as the device path. | IMPLEMENTED | [`boltrig/kernel/camera_agent_routes.py:230`](../../../boltrig/kernel/camera_agent_routes.py) `"return _error(\"invalid_camera_lease_signature\", 403)"` | - |
| BT-REQ-1425 | Owner-facing camera binding and lease reads require actor tier human. | IMPLEMENTED-UNTESTED | [`boltrig/kernel/camera_agent_routes.py:170`](../../../boltrig/kernel/camera_agent_routes.py) `"return _error(\"human_required\", 403)"` (bounded: rg -n human_required tests/, 2026-08-24, no hits) | - |
| BT-REQ-1426 | The camera lease adapter is the adapter registered at bootstrap; the read-only camera discovery adapter is not. | IMPLEMENTED | [`boltrig/api/camera_bootstrap.py:19`](../../../boltrig/api/camera_bootstrap.py) `"build_camera_lease_adapter(kernel.store, signer)"` | - |
| BT-REQ-1427 | The device-side verifier independently refuses a camera lease whose validity window exceeds three minutes or whose issued_at is more than thirty seconds ahead. | IMPLEMENTED-UNTESTED | [`apps/worker/src-tauri/src/camera_protocol.rs:85`](../../../apps/worker/src-tauri/src/camera_protocol.rs) `"expires_at - issued_at > time::Duration::minutes(3)"` | - |
| BT-REQ-1428 | The device re-checks the live camera descriptor fingerprint against the lease before performing any UVC operation. | IMPLEMENTED-UNTESTED | [`apps/worker/src-tauri/src/camera_discovery.rs:488`](../../../apps/worker/src-tauri/src/camera_discovery.rs) `"return Err(\"camera_descriptor_changed\".to_string());"` | - |
| BT-REQ-1429 | The shipped camera identity and descriptor fingerprint are both sha256 over a USB topology string, and the camera id is its first 32 hex characters. | IMPLEMENTED-UNTESTED | [`apps/worker/src-tauri/src/camera_discovery.rs:675`](../../../apps/worker/src-tauri/src/camera_discovery.rs) `"let camera_id = format!(\"camera_{}\", &descriptor_fingerprint[..32]);"` | - |
| BT-REQ-1430 | The Python and Rust camera action digests agree, pinned by a shared fixture value. | IMPLEMENTED | [`apps/worker/src-tauri/src/camera_protocol.rs:298`](../../../apps/worker/src-tauri/src/camera_protocol.rs) `"fn rust_matches_python_camera_action_digest_fixture() {"` | - |
| BT-REQ-1431 | The device agent holds at most one pending camera claim and persists it before executing, so a crash still settles on the next cycle. | IMPLEMENTED-UNTESTED | [`apps/worker/src-tauri/src/device_agent.rs:512`](../../../apps/worker/src-tauri/src/device_agent.rs) `"agent.pending_camera_claim = Some(PendingClaim {"` | - |
| BT-REQ-1432 | The six sensing settings keys are owned by sensing_policy and refused by the generic settings write route. | IMPLEMENTED | [`tests/security/test_sensing_settings.py:134`](../../../tests/security/test_sensing_settings.py) `"def test_the_generic_settings_bag_cannot_turn_the_camera_on() -> None:"` | - |
| BT-REQ-1433 | A fresh Boltrig has both the camera and presence off, and reports the difference between a safe default and a user override. | IMPLEMENTED | [`boltrig/kernel/sensing_policy.py:230`](../../../boltrig/kernel/sensing_policy.py) `"\"source\": \"user_override\" if CAMERA_ENABLED in rows else \"safe_default\","` | - |
| BT-REQ-1434 | Every sensing write requires an interactive human credential, not merely a human actor tier. | IMPLEMENTED | [`tests/security/test_sensing_settings.py:149`](../../../tests/security/test_sensing_settings.py) `"def test_a_machine_credential_cannot_turn_the_users_camera_on() -> None:"` | - |
| BT-REQ-1435 | Binding a camera that no device agent has published is refused at write time with 409 camera_binding_unavailable and the attempt is audited. | IMPLEMENTED | [`tests/security/test_sensing_settings.py:169`](../../../tests/security/test_sensing_settings.py) `"def test_an_unpublished_camera_is_refused_at_write_time_and_the_change_is_audited() -> None:"` | - |
| BT-REQ-1436 | Presence cannot be enabled without a room-calibrated threshold, and the served config never reports presence enabled without one. | IMPLEMENTED | [`tests/security/test_sensing_settings.py:196`](../../../tests/security/test_sensing_settings.py) `"def test_presence_cannot_be_turned_on_without_a_room_calibrated_threshold() -> None:"` | - |
| BT-REQ-1437 | The enrolled face is stored as metadata only, is named as never leaving the kernel, and is reported as not exportable on every projection. | IMPLEMENTED | [`boltrig/kernel/sensing_policy.py:72`](../../../boltrig/kernel/sensing_policy.py) `"NEVER_LEAVES_THE_KERNEL = frozenset({ENROLLMENT})"` | - |
| BT-REQ-1438 | The effective capture policy is served to a device-authenticated caller and answered for that device's owner, never for another principal. | IMPLEMENTED | [`boltrig/kernel/camera_agent_routes.py:296`](../../../boltrig/kernel/camera_agent_routes.py) `"settings = await sensing_settings(kernel.store, device.tenant_id, device.owner_id)"` | - |
| BT-REQ-1439 | A refused sensing capability answers status refused with a named reason and 409, never 403 and never an error. | IMPLEMENTED | [`boltrig/kernel/sensing_routes.py:217`](../../../boltrig/kernel/sensing_routes.py) `"status = 200 if decision[\"status\"] == \"granted\" else 409"` | - |
| BT-REQ-1440 | The sensing capability route governs consent only; it carries no character identity and does not enforce declaration. | IMPLEMENTED | [`tests/security/test_sensing_settings.py:102`](../../../tests/security/test_sensing_settings.py) `"def test_the_kernel_does_not_know_which_character_is_asking() -> None:"` | - |
| BT-REQ-1441 | The served config carries a maximum staleness of 3600 seconds after which a host stands down without releasing the device. | IMPLEMENTED | [`boltrig/kernel/sensing_policy.py:106`](../../../boltrig/kernel/sensing_policy.py) `"CONFIG_MAX_STALE_S = 3600"` | - |
| BT-REQ-1442 | The kernel's only emotion touch is the relay factory call in Kernel.__init__. | IMPLEMENTED | [`boltrig/kernel/__init__.py:79`](../../../boltrig/kernel/__init__.py) `"self.events = build_emotion_relay(backend=event_relay)"` | EMO-1 |
| BT-REQ-1443 | No exception in the emotion path can escape publish, the publisher thread, table loading or the relay factory. | IMPLEMENTED | [`boltrig/emotion/relay.py:106`](../../../boltrig/emotion/relay.py) `"cosmetic channel, never let it touch a run"` | P9 |
| BT-REQ-1444 | The emotion engine reads no clock, performs no I/O and uses no randomness; time enters only through now arguments. | IMPLEMENTED | [`tests/emotion/test_engine.py:229`](../../../tests/emotion/test_engine.py) `"def test_engine_module_imports_stay_inside_the_pure_whitelist() -> None:"` | EMO-3 |
| BT-REQ-1445 | Tension decays with a real 1.4 second half-life and is never tempo-scaled. | IMPLEMENTED | [`boltrig/emotion/engine.py:142`](../../../boltrig/emotion/engine.py) `"self._tension = _clamp01(self._tension * math.pow(0.5, dt / 1.4))"` | EMO-3 |
| BT-REQ-1446 | Attachment accumulates only from appraisal deltas, decays on a real-days half-life, and affects only the effective baselines emotions decay toward. | IMPLEMENTED | [`tests/emotion/test_engine.py:322`](../../../tests/emotion/test_engine.py) `"def test_attachment_decays_in_real_days_never_tempo_scaled() -> None:"` | EMO-6 |
| BT-REQ-1447 | The phenotype projection is exactly ten scalars, each clamped to 0..1, derived and never stored. | IMPLEMENTED | [`boltrig/emotion/engine.py:221`](../../../boltrig/emotion/engine.py) `"The ten observable scalars (each 0..1), after decaying state to"` | EMO-2 |
| BT-REQ-1448 | The emotion model, appraisals and event map are YAML data, and any load failure leaves the feature off rather than raising. | IMPLEMENTED | [`boltrig/emotion/tables.py:190`](../../../boltrig/emotion/tables.py) `"P9: any load failure keeps the feature off"` | EMO-5 |
| BT-REQ-1449 | The emotion relay is enabled by BOLTRIG_EMOTION, falling back to whether orbctl is on PATH. | IMPLEMENTED | [`boltrig/emotion/relay.py:358`](../../../boltrig/emotion/relay.py) `"return shutil.which(\"orbctl\") is not None"` | EMO-1 |
| BT-REQ-1450 | Both emotion files are written through a unique mkstemp, chmod 0644 and os.replace, never through a fixed temporary name. | IMPLEMENTED-UNTESTED | [`boltrig/emotion/relay.py:340`](../../../boltrig/emotion/relay.py) `"fd, tmp = tempfile.mkstemp(prefix=f\".{path.name}-\", dir=str(path.parent))"` (bounded: rg -n mkstemp tests/emotion/, 2026-08-24, no hits) | - |
| BT-REQ-1451 | The publisher thread writes the phenotype every tick and the tenant state snapshot every twentieth tick. | IMPLEMENTED-UNTESTED | [`boltrig/emotion/relay.py:41`](../../../boltrig/emotion/relay.py) `"_STATE_EVERY_TICKS = 20"` (bounded: rg -n _STATE_EVERY_TICKS tests/, 2026-08-24, no hits) | - |
| BT-REQ-1452 | An emotion reset replaces the tenant engine at model baselines and drops the persisted restore snapshot so a restart cannot resurrect the old mood. | IMPLEMENTED | [`tests/emotion/test_affordances.py:74`](../../../tests/emotion/test_affordances.py) `"def test_reset_also_drops_the_persisted_restore_snapshot(tmp_path: pathlib.Path) -> None:"` | - |
| BT-REQ-1453 | A character adoption is appraised at most once per sixty seconds per tenant, so cycling skins cannot pump the mood. | IMPLEMENTED | [`libraries/emotion/event_map.yaml:39`](../../../libraries/emotion/event_map.yaml) `"appraise: character_adopted, intensity: 1.0, throttle_s: 60"` | - |
| BT-REQ-1454 | Every failure of the phenotype route answers the resting shape with fresh false, never an error status. | IMPLEMENTED | [`tests/emotion/test_phenotype_projection.py:27`](../../../tests/emotion/test_phenotype_projection.py) `"def test_missing_stale_or_malformed_files_all_answer_resting(tmp_path, monkeypatch):"` | EMO-7 |
| BT-REQ-1455 | The phenotype route module imports nothing from boltrig.emotion. | IMPLEMENTED | [`tests/emotion/test_phenotype_projection.py:83`](../../../tests/emotion/test_phenotype_projection.py) `"def test_projection_module_never_imports_the_emotion_package():"` | EMO-7 |
| BT-REQ-1456 | The phenotype route reads a process-wide runtime file and does not scope its answer by the authenticated principal. | IMPLEMENTED-UNTESTED | [`boltrig/kernel/familiar_phenotype_routes.py:84`](../../../boltrig/kernel/familiar_phenotype_routes.py) `"return read_phenotype_projection()"` | - |
| BT-REQ-1457 | familiar.express is a registered verb with a closed eight-member gesture enum, additionalProperties false, and a ttl capped at fifteen seconds. | IMPLEMENTED | [`tests/security/test_familiar_express.py:58`](../../../tests/security/test_familiar_express.py) `"async def test_familiar_express_is_registered_with_a_binding(monkeypatch, tmp_path):"` | WL-3 |
| BT-REQ-1458 | The express channel is written only by the dispatched handler, and an ungranted or schema-invalid call writes nothing. | IMPLEMENTED | [`tests/security/test_familiar_express.py:75`](../../../tests/security/test_familiar_express.py) `"async def test_ungranted_express_is_denied_audited_and_writes_nothing(monkeypatch, tmp_path):"` | WL-3 |
| BT-REQ-1459 | The desktop hands verbs, the shared registry and the /v1/hands surface exist only when BOLTRIG_DESKTOP_HANDS is set. | IMPLEMENTED | [`tests/security/test_desktop_hands.py:237`](../../../tests/security/test_desktop_hands.py) `"async def test_desktop_verbs_only_exist_when_the_addon_is_enabled(monkeypatch):"` | DH-1 |
| BT-REQ-1460 | A pending desktop command expires after thirty seconds and is claimed mark-on-read, so it can never be delivered to two polls. | IMPLEMENTED | [`tests/security/test_desktop_hands.py:183`](../../../tests/security/test_desktop_hands.py) `"async def test_hands_routes_claim_once_and_record_the_receipt():"` | DH-1 |
| BT-REQ-1461 | A desktop dispatch waits eight seconds for its receipt, strictly less than the registry TTL, and reports executor_offline on timeout with the audit row standing. | IMPLEMENTED | [`tests/security/test_desktop_hands.py:150`](../../../tests/security/test_desktop_hands.py) `"async def test_executor_offline_still_dispatches_and_audits():"` | DH-1 |
| BT-REQ-1462 | A receipt for an unknown or expired command id returns 404 and writes no audit row. | IMPLEMENTED | [`boltrig/kernel/desktop_routes.py:82`](../../../boltrig/kernel/desktop_routes.py) `"was never issued): refuse, and do not audit a no-op as execution"` | DH-1 |
| BT-REQ-1463 | The hands registry is kernel-global and applies no tenant partition to the pull surface. | IMPLEMENTED-UNTESTED | [`boltrig/kernel/desktop_routes.py:61`](../../../boltrig/kernel/desktop_routes.py) `"for cmd in reg.pending():"` | - |
| BT-REQ-1464 | The Familiar carries six modes and resolves them by the fixed precedence failure, speaking, listening, working, thinking, standby. | IMPLEMENTED | [`apps/worker/src/components/familiar/FamiliarState.ts:119`](../../../apps/worker/src/components/familiar/FamiliarState.ts) `"if (input.failed) mode = \"error\";"` | - |
| BT-REQ-1465 | FamiliarStageState carries only a closed mode enum and clamped 0..1 numbers, accepting a bands array only at length eight. | IMPLEMENTED | [`apps/worker/src/components/familiar/FamiliarState.ts:76`](../../../apps/worker/src/components/familiar/FamiliarState.ts) `"const bands = Array.isArray(next.bands) && next.bands.length === 8"` | - |
| BT-REQ-1466 | The Familiar's host-side behaviour is a 24 field numeric tuning struct with per-mode deltas layered over it. | IMPLEMENTED | [`apps/worker/src/components/canvas/familiarPresets.ts:182`](../../../apps/worker/src/components/canvas/familiarPresets.ts) `"return { ...FAMILIAR_TUNING, ...FAMILIAR_MODES[mode] };"` | - |
| BT-REQ-1467 | The Stage falls back to the CSS badge the moment the WebGL2 renderer reports failed, and never rewrites the look to survive a failure. | IMPLEMENTED | [`apps/worker/src/components/familiar/useFamiliarRenderer.ts:52`](../../../apps/worker/src/components/familiar/useFamiliarRenderer.ts) `"if (renderer.status().state === \"failed\") setKind(\"badge\");"` | - |
| BT-REQ-1468 | The Stage announces its state through an aria-live region that is a sibling of the role=img body, never nested inside it. | IMPLEMENTED | [`apps/worker/src/components/familiar/FamiliarStage.tsx:71`](../../../apps/worker/src/components/familiar/FamiliarStage.tsx) `"<span aria-live=\"polite\" className=\"familiar-stage-status\">"` | - |
| BT-REQ-1469 | A stale or absent phenotype is handed to the renderer as null, so the inner life resumes wandering rather than holding a stale expression. | IMPLEMENTED | [`apps/worker/src/components/familiar/useFamiliarRenderer.ts:72`](../../../apps/worker/src/components/familiar/useFamiliarRenderer.ts) `"phenotype?.fresh && phenotype.phenotype ? phenotype.phenotype : null,"` | - |
| BT-REQ-1470 | The renderer ladder ships two rungs, the CSS badge and webgl2; the Unreal tier is deferred and absent from the tree. | IMPLEMENTED | [`apps/worker/src/components/familiar/useFamiliarRenderer.ts:19`](../../../apps/worker/src/components/familiar/useFamiliarRenderer.ts) `"export type FamiliarRendererKind"` (bounded: grep -rni unreal over apps/ boltrig/ sdks/ familiar/ for .ts, .tsx, .py and .rs, 2026-08-24, one hit, a comment in sdks/web/src/familiarState.ts naming it as later) | - |
| BT-REQ-1471 | The Familiar genotype is derived from the canonical capability name alone and carries no runtime, grant, model or mood state. | IMPLEMENTED | [`tests/unit/test_familiar_identity.py:24`](../../../tests/unit/test_familiar_identity.py) `"def test_genotype_projection_contains_no_authority_or_runtime_state():"` | SEC-WRK-10 |
| BT-REQ-1472 | The genotype packs into a positional 32 slot uniform array whose defaults reproduce the neutral circle, and appending is the only safe change. | IMPLEMENTED-UNTESTED | [`familiar/genotype.h:33`](../../../familiar/genotype.h) `"The array grows in whole vec4s and only ever at the END"` (no C test target in this repo; the Worker twin is covered by apps/worker/tests/familiarBundle.test.ts) | - |
| BT-REQ-1473 | The Worker's vendored familiar.frag is byte-identical to the in-repo canon and to the sha256 pinned by its bundle manifest. | IMPLEMENTED | [`apps/worker/tests/familiarShaderParity.test.ts:17`](../../../apps/worker/tests/familiarShaderParity.test.ts) `"worker's vendored familiar.frag is byte-identical to the canon"` | - |
| BT-REQ-1474 | FamiliarState v2 is a defined, sanitised, content-free contract with no producer and no consumer in this tree. | SCAFFOLDED | [`sdks/web/src/familiarState.ts:67`](../../../sdks/web/src/familiarState.ts) `"export interface FamiliarStateV2 {"` | - |
| BT-REQ-1475 | The desktop familiar consumes nine phenotype scalars and does not read the attachment scalar. | IMPLEMENTED-UNTESTED | [`familiar/main.c:110`](../../../familiar/main.c) `"float valence, arousal, irritation, fatigue, attention,"` | - |
| BT-REQ-1476 | The desktop familiar surface imports nothing from boltrig and couples only through the versioned phenotype file, checked statically. | IMPLEMENTED | [`familiar/check.sh:9`](../../../familiar/check.sh) `"WL-1: the surface imports nothing from boltrig; it consumes only the phenotype file"` | - |
| BT-REQ-1477 | Absence of a compositor, a GPU or a phenotype degrades the desktop familiar to a typed message or the resting baseline, never a crash. | IMPLEMENTED | [`familiar/check.sh:19`](../../../familiar/check.sh) `"WL-2: no compositor / no GPU / no phenotype degrades typed, never crashes"` | - |
| BT-REQ-1478 | make install runs the severance and layer-hygiene check, so a build that would cover the KVM capture strip cannot be installed. | IMPLEMENTED | `familiar/Makefile:49` install: all check | - |
| BT-REQ-1479 | BOLTRIG_ADDONS naming an unregistered addon raises rather than shipping a build with no integration seam. | IMPLEMENTED | [`boltrig/addons/__init__.py:167`](../../../boltrig/addons/__init__.py) `"names unregistered addon(s)"` | - |
| BT-REQ-1480 | An addon harness fragment is bounded to 4096 bytes so it cannot push the governance floor out of the model's attention. | IMPLEMENTED | [`boltrig/addons/__init__.py:119`](../../../boltrig/addons/__init__.py) `"harness exceeds {MAX_ADDON_HARNESS_BYTES} bytes"` | - |
| BT-REQ-1481 | At most one active addon may claim the on-behalf adapter id; two is refused rather than resolved by picking one. | IMPLEMENTED | [`boltrig/addons/__init__.py:199`](../../../boltrig/addons/__init__.py) `"more than one active addon claims the on-behalf adapter"` | - |
| BT-REQ-1482 | Consequence hints are read from every registered addon and the highest tier wins, so one addon's low can never mask another's high. | IMPLEMENTED | [`boltrig/addons/__init__.py:208`](../../../boltrig/addons/__init__.py) `"The HIGHEST consequence any addon reads off"` | - |
| BT-REQ-1483 | An installed package's entry-point addon may not replace a name this build already registers. | IMPLEMENTED | [`boltrig/addons/__init__.py:311`](../../../boltrig/addons/__init__.py) `"would replace the already"` | - |
| BT-REQ-1484 | The pinned birth profile version composes the active addons as semver build metadata rather than forking a second lineage. | IMPLEMENTED | [`boltrig/addons/__init__.py:184`](../../../boltrig/addons/__init__.py) `"return f\"{base_version}+{parts}\""` | - |
| BT-REQ-1485 | The product name is derived at runtime from the active addons and served at GET /v1/branding, never baked into a client bundle. | IMPLEMENTED | [`tests/unit/test_branding.py:62`](../../../tests/unit/test_branding.py) `"assert response.json() == {\"product_name\": product_name(), \"pulse\": True}"` | - |
| BT-REQ-1486 | The addon runtime inventory is read-only, tenant and workspace scoped, and never serializes harness text, refs, values or evaluator faults. | IMPLEMENTED | `tests/security/test_addon_inventory.py::test_inventory_redacts_private_declarations_and_evaluator_faults` | SEC-WRK-26 |
| BT-REQ-1487 | A camera profile is declarative TOML with a closed top-level key set and is refused if it carries any command, exec, module, script, download or url key. | IMPLEMENTED | [`tests/camera/test_discovery.py:174`](../../../tests/camera/test_discovery.py) `"def test_profile_loader_rejects_executable_metadata() -> None:"` | - |
| BT-REQ-1488 | A profile match is a routing hint only; vendor metadata stays inactive unless the profile id is in an explicit trusted set. | IMPLEMENTED | [`tests/camera/test_discovery.py:76`](../../../tests/camera/test_discovery.py) `"def test_profile_match_is_not_proof_and_vendor_metadata_stays_inactive() -> None:"` | - |
| BT-REQ-1489 | The camera knowledge cache stores only a digest of the platform hardware key and never a raw serial, registry path or probe payload. | IMPLEMENTED | [`tests/camera/test_discovery.py:161`](../../../tests/camera/test_discovery.py) `"def test_cache_never_persists_probe_or_serial_fields(tmp_path: Path) -> None:"` | - |
| BT-REQ-1490 | Discovery grants a mutating camera verb only where the current evidence proves it, and an unknown HID camera never gains one. | IMPLEMENTED | [`tests/camera/test_discovery.py:96`](../../../tests/camera/test_discovery.py) `"def test_unknown_hid_camera_never_gains_mutating_vendor_verbs() -> None:"` | - |
| BT-REQ-1491 | The read-only camera discovery adapter refuses camera.snapshot unless the capability state is proven. | IMPLEMENTED | [`tests/camera/test_camera_adapter.py:76`](../../../tests/camera/test_camera_adapter.py) `"async def test_camera_adapter_does_not_expose_unproven_snapshot() -> None:"` | - |
| BT-REQ-1492 | The boltrig.camera discovery package and the read-only camera adapter are reachable only from tests, not from any production entrypoint. | DEAD | bounded rg over the pinned tree, 2026-08-24 (grep -rn boltrig.camera over *.py), returns only tests/camera/*; [`boltrig/api/camera_bootstrap.py:19`](../../../boltrig/api/camera_bootstrap.py) `"build_camera_lease_adapter(kernel.store, signer)"` registers the lease adapter instead | - |
| BT-REQ-1493 | The device presence value locked is declared by the schema and the SDK and is never written by any code path. | DEAD | [`migrations/versions/0042_desktop_devices.py:42`](../../../migrations/versions/0042_desktop_devices.py) `"CHECK (presence IN ('offline','online','locked','revoked')),"` (no writer found; bounded: grep -rnw locked over boltrig/ apps/ sdks/ migrations/ tests/, 2026-08-24, whose only device-presence hits are the enum, the SDK type and this CHECK) | - |
| BT-REQ-1494 | The device lease verb constraint admits device.file.list only from migration 0072, whose downgrade refuses while such leases exist. | IMPLEMENTED | [`migrations/versions/0072_device_workspace_snapshots.py:51`](../../../migrations/versions/0072_device_workspace_snapshots.py) `"RAISE EXCEPTION 'device workspace snapshot leases still exist'"` | - |
| BT-REQ-1495 | Every device and camera table enables and forces row level security with a tenant_isolation policy on app.tenant_id. | IMPLEMENTED | tests/security/test_rls_fence_coverage.py::test_every_tenant_table_is_rls_fenced_or_documented_excluded | - |
| BT-REQ-1496 | Desktop hands verbs that change host state carry idempotency mode disabled so a replayed receipt cannot claim an undelivered action. | IMPLEMENTED | [`boltrig/adapters/builtin/desktop.py:107`](../../../boltrig/adapters/builtin/desktop.py) `"idempotency_mode=\"disabled\","` | DH-1 |
| BT-REQ-1497 | The camera lease verbs are declared idempotency mode cacheable, unlike the state-changing desktop verbs. | IMPLEMENTED-UNTESTED | [`boltrig/adapters/builtin/camera_leases.py:32`](../../../boltrig/adapters/builtin/camera_leases.py) `"\"idempotency_mode\": \"cacheable\","` | - |
| BT-REQ-1498 | The face enrolment is published by the host agent over the device transport and forgotten by the human over the owner routes; there is no browser route that records one. | IMPLEMENTED | [`boltrig/kernel/sensing_routes.py:165`](../../../boltrig/kernel/sensing_routes.py) `"Recording an enrolment is NOT here"` | - |
| BT-REQ-1499 | Deployment shape for these surfaces is expressed by provisioning and runtime signals rather than by build-time flags. | IMPLEMENTED | [`boltrig/branding.py:8`](../../../boltrig/branding.py) `"WHY THIS IS DERIVED FROM THE ADDON AND NOT FROM A BUILD FLAG"` | - |
