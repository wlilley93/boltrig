# EMEET Pixy hardware report — 2026-08-10

## Scope and safety

This report records the initial read-only session and the subsequent guarded
physical-control test against the attached EMEET Pixy on a Mac running macOS
26.0 (Darwin 25.2.0). EMEET Studio was not installed or used. No EMEET account
was created, firmware was not updated, and no audio was captured. The only
control writes were the two deliberately bounded standard-UVC PTZ movements
and their exact restorations documented below; no proprietary HID output was
sent.

The native probe is [tools/pixy-probe](../../tools/pixy-probe/README.md). Its
default JSON intentionally excludes the USB serial number, registry path,
persistent hardware UUID, and raw HID payloads.

## Exact device identity

| Field | Measured value |
| --- | --- |
| Manufacturer | EMEET |
| Product | EMEET PIXY |
| VID | `0x328F` |
| PID | `0x00C0` |
| USB version | `2.00` |
| Device class | `0xEF / 0x02 / 0x01` (miscellaneous composite) |
| Current USB configuration | 1 |
| Reported USB speed | High speed (`Device Speed = 2`) |

The serial number was observed locally but is deliberately not recorded here.

## USB interfaces

The active configuration contains one UVC function, one UAC function, and one
HID function:

| Interface(s) | Class | Observation |
| --- | --- | --- |
| 0 | Video control (`0x0E/0x01`) | UVC 1.00; one control endpoint |
| 1, alternate settings 0–11 | Video streaming (`0x0E/0x02`) | Eleven streaming alternates |
| 2 | Audio control (`0x01/0x01`) | Standard USB Audio control interface |
| 3, alternate settings 0–1 | Audio streaming (`0x01/0x02`) | Standard USB Audio streaming interface |
| 4 | HID (`0x03/0x00/0x00`) | Two endpoints; vendor-defined report collection |

No CDC Ethernet, RNDIS, NCM, or wireless-class interface was present. No
secondary/AI camera appeared as a separate macOS video device; AVFoundation
enumerated exactly one Pixy video device.

## Standard video capture

macOS recognised the main camera through AVFoundation/UVC as `EMEET PIXY`.
The probe enumerated these modes; frame rates are rounded to the device's
reported 30/60 fps values:

| Resolution | Pixel format | Frame rate |
| --- | --- | --- |
| 640×360 | `yuvs` | 30 |
| 640×360 | `420v` | 30, 60 |
| 640×480 | `yuvs` | 30 |
| 640×480 | `420v` | 30 |
| 800×600 | `420v` | 30 |
| 960×720 | `420v` | 30 |
| 1024×576 | `420v` | 30, 60 |
| 1280×720 | `420v` | 30, 60 |
| 1280×960 | `420v` | 30 |
| 1920×1080 | `420v` | 30, 60 |
| 2560×1440 | `420v` | 30 |
| 3840×2160 | `420v` | 30 |

One and only one local test frame was captured without EMEET software at
3840×2160 from the UVC device using UYVY input and JPEG output:

| Field | Value |
| --- | --- |
| Width × height | 3840×2160 |
| Encoded media type | JPEG |
| Encoded size | 126,953 bytes |
| SHA-256 | `49971c762d1d3c5cf34b3d7004fd03a9f0f431159bbd18f39199e606cd4189bc` |

The frame was deleted after inspection and was not committed or uploaded.

AVFoundation reported continuous autofocus and continuous auto-exposure as
supported. The current reported modes were locked focus and locked exposure;
the probe did not change either mode, so behaviour after switching them still
needs a separate, explicitly controlled test. No white-balance mode was
reported as supported by AVFoundation.

## UAC microphone

The Pixy microphone enumerated as standard USB Audio (`EMEET PIXY`) with one
input channel at 48 kHz in the macOS audio inventory. Enumeration only was
performed. Boltrig Vision must not claim microphone ownership in this pass.

## UVC control descriptor results

The camera terminal advertised these standard UVC controls. A read-only
`GET_INFO` request reported both GET and SET support for each control. The
device returns malformed/non-standard `GET_LEN` values for several controls;
the guarded PTZ test therefore used the standard fixed UVC lengths for the
control types, rather than trusting those lengths.

| Control | Advertised | GET_INFO readable | GET_INFO writable | Range/current readback |
| --- | --- | --- | --- | --- |
| Exposure mode | yes | yes | yes | raw three-byte responses; not used for this test |
| Exposure absolute | yes | yes | yes | raw three-byte responses; not used for this test |
| Focus absolute | yes | yes | yes | min 0, max 1023, step 1, default 192, current 454 |
| Zoom absolute | yes | yes | yes | min 100, max 150, step 1, default 100, current 100 |
| Pan/Tilt absolute | yes | yes | yes | fixed-length 8-byte readback verified below |
| Privacy | yes | yes | yes | fixed-length 1-byte reads all returned `0x03`; invalid UVC boolean |

The focus and zoom values were read only; neither was written.

## Guarded physical PTZ test

The exact device was re-identified immediately before each test as EMEET /
VID `0x328F` / PID `0x00C0`, matching the previously probed Pixy. The UVC
Camera Terminal was interface 0, terminal ID 1. PTZ used only standard UVC
Camera Terminal selector `0x0D` (`PAN_TILT_ABSOLUTE`): eight-byte signed
little-endian pan/tilt values, `GET_*` requests with `bmRequestType 0xA1`, and
`SET_CUR` with `bmRequestType 0x21`. No HID report, focus write, or zoom write
was issued.

All coordinates below are UVC units of **one arc-second** (UVC 1.5 Table 4-12), not
`0.01 degree` as originally recorded here. The table itself settles it: a step of
3600 is exactly 1.000 degree in arc-seconds, whereas under `0.01 degree` the step
would be 36 degrees and the range fifteen full rotations rather than a plausible
±150° pan / ±90° tilt. Read correctly, the advertised range is ±150° pan, ±90° tilt,
in 1° steps.

The complete advertised readback was:

| Value | Pan | Tilt |
| --- | ---: | ---: |
| Starting/current | 0 | 0 |
| Minimum | -540000 | -324000 |
| Maximum | 540000 | 324000 |
| Step | 3600 | 3600 |
| Default | 0 | 0 |

One positive advertised step (`+3600`, or `+36.00°`) was selected for each
axis. This remained far inside the advertised limits.

| Test | Starting PTZ | Requested delta / position | Read-back after movement | Physical movement | Exact restoration | Errors |
| --- | --- | --- | --- | --- | --- | --- |
| Pan | `[0, 0]` | `+3600` / `[3600, 0]` | `[3600, 0]` | Confirmed from before/during local 640×360 UVC frames | `SET_CUR [0, 0]`; read back `[0, 0]` | None |
| Tilt | `[0, 0]` | `+3600` / `[0, 3600]` | `[0, 3600]` | Confirmed from before/during local 640×360 UVC frames | `SET_CUR [0, 0]`; read back `[0, 0]` | None |

The pan frame changed from the ceiling/fixture view to the operator/desk view;
the tilt frame changed the vertical framing of the operator and keyboard. The
temporary frames were inspected locally and deleted. Both tests returned an
8-byte successful `SET_CUR`, both read-backs matched the requested target, and
both exact restorations returned an 8-byte successful `SET_CUR` followed by
`[0, 0]`. All libusb/UVC handles were closed after each test. The final PTZ
state is `[0, 0]`.

This proves standard UVC PTZ is genuinely writable, readable, and physically
actuating on this Pixy. Standard UVC is the production PTZ mechanism; no
proprietary PTZ search or HID experiment is warranted.

## Privacy investigation

Privacy is advertised in the standard UVC Camera Terminal as selector `0x11`,
not as a vendor-specific HID control. `GET_INFO` returned `0x03`, indicating
readable and writable. However, `GET_LEN` returned `0x0300`, and standard
fixed-length one-byte reads returned `0x03` for minimum, maximum, resolution,
default, and current. A UVC privacy control is boolean, so `0x03` is outside
the valid `0`/`1` domain and its semantics are not sufficiently clear for a
safe enable write.

No privacy `SET_CUR` was sent. A normal UVC frame was still obtainable in the
untouched final state, so no stream suppression or host-side capture closure
was observed. Physical lens/shutter or gimbal privacy was not established.
The safest proven state is therefore the unchanged privacy state, PTZ at
`[0, 0]`, and no open capture/control handles.

## HID descriptor results

Interface 4 is present and was opened only for descriptor reads. It has a
vendor-defined collection at usage page `0x0083`, usage `0x0083`, with report
ID 9:

| Report | Size |
| --- | --- |
| Input | 32 bytes |
| Output | 32 bytes |

The HID report descriptor is 35 bytes. No input report was logged and no
output report was sent. No tracking, gesture, privacy, or other proprietary
HID behaviour is assumed from this descriptor alone.

## Network observation

The camera was already connected when this session began, so this is not a
controlled unplug/replug delta. The following observations were made while
using standard UVC capture without EMEET software:

- the Pixy configuration contained no network-class USB interface;
- `networksetup -listallhardwareports` and `ifconfig -l` showed no EMEET- or
  Pixy-named network interface;
- no EMEET process or installed EMEET application path was found;
- the UVC capture process had no TCP or UDP socket ownership in `lsof`;
- existing DNS servers, listeners, and outbound TCP/UDP connections belonged
  to unrelated macOS applications/services and were not attributed to the
  camera;
- no packet-interception certificate was installed and TLS was not weakened.

Conclusion for this session: the wired device behaves as a standard USB
camera/audio/HID composite, with no observed host network interface or
camera-owned network socket. A controlled reconnect plus packet-level capture
can be added later if stronger timing evidence is required.

## Capability gate

### Proven enough to design around

- standard UVC video capture;
- one-shot local snapshot at 4K/30-capable mode;
- standard UAC microphone enumeration only;
- descriptor-level UVC control advertisement;
- standard UVC pan/tilt writes, read-back, physical movement, and exact
  restoration;
- local HID descriptor presence, without proprietary semantics;
- no observed camera network interface.

### Not proven and must remain unsupported

- zoom/focus writes through UVC;
- privacy enable/disable semantics or physical lens/gimbal closure;
- onboard tracking activation;
- gesture control;
- secondary/AI camera metadata;
- any proprietary HID command.

The immediate Boltrig implementation boundary remains governed camera
discovery/status and evidence-backed capability projection. The PTZ hardware
gate is complete for Pixy and standard UVC is the production mechanism. The
generic Worker now has a bounded native UVC backend and root-free signed camera
lease transport; a PTZ write lease remains unavailable until the Worker has
published a proven binding from guarded physical verification. Tracking,
privacy writes, and continuous observation remain unsupported.

## Boltrig architecture gate

The current Worker device path remains a file/argv lease surface: the Python
`device` adapter publishes only `device.file.read`, `device.file.write`, and
`device.command.run`. Camera work is a separate native backend and lease
transport. It re-identifies the exact descriptor fingerprint, reads standard
UVC controls, captures at most one bounded local frame for proof, and performs
only semantic PTZ actions. It is never routed through `device.command.run`,
arbitrary USB access, or raw HID.

The server persists opaque camera bindings and separate root-free signed
`camera.ptz.get` / `camera.ptz.set` leases. The Worker publishes bounded
observations over the authenticated device session, claims the exact signed
lease, rechecks the descriptor locally, executes standard UVC, and settles a
bounded receipt. A PTZ write lease requires a published proven binding and an
exact consumed human approval. Zoom, focus, privacy writes, and proprietary HID
remain outside the public schema.

The generic Camera Discovery v1 foundation now lives in
[`docs/hardware/CAMERA-DISCOVERY-v1.md`](CAMERA-DISCOVERY-v1.md), with Pixy as
the first redacted golden fixture. It uses explicit capability states and
evidence, local declarative profiles/quirks, and opaque local binding/cache
contracts. The Worker now has AVFoundation inventory/hotplug and bounded-capture
support, diagnostics UI, a generic libusb UVC PTZ backend, and a separate
descriptor-bound signed camera-lease executor. No Pixy-specific PTZ
implementation or HID fallback is enabled.
