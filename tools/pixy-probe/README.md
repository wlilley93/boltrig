# Pixy probe

This directory contains a macOS-only read-only diagnostic plus a separately
invoked, narrowly guarded standard-UVC PTZ test for the physically attached
EMEET Pixy. Neither tool installs EMEET Studio, creates an account, updates
firmware, or captures audio. The default probe never sends HID output reports
or writes UVC controls. The live test sends only one advertised-step PTZ
movement and restores the exact starting position.

The default report is safe to paste into an issue:

- no USB serial number, registry path, persistent hardware UUID, or raw HID
  report bytes;
- USB identity is limited to manufacturer/product and VID/PID;
- UVC control values are included only when they can be read through standard
  read-only UVC requests;
- video formats are enumerated through AVFoundation without starting capture.

Build and run from the repository root:

```sh
make -C tools/pixy-probe
tools/pixy-probe/build/pixy-probe
```

The binary exits successfully when the Pixy is absent and reports
`device.present: false`; it is not a live motor test.

### GET_LEN cannot be trusted for pan/tilt

The Pixy answers `GET_LEN` for `PAN_TILT_ABSOLUTE` with **3**, which is not a legal
width for an eight-byte control. Honouring it produced truncated reads that decoded to
nothing, so `min`, `max`, `step`, `default` and `current` were all reported `null` for a
camera whose standard eight-byte reads succeed perfectly — a working PTZ device looking
unreadable in the very report used to prove support. The probe now keeps the known
fixed width for pan/tilt and privacy and records the discarded value as
`get_len_ignored`. The Worker bridge (`camera_uvc.m`) already did this.

Note the same quirk is declared three times in different forms:
`camera-profiles/emeet-pixy/profile.toml` (`ignore_get_len`, `fixed_length`), and
hardcoded in both native tools. Nothing reads the profile keys — they are documentation
until a loader wires them into the native path, so the two can drift apart.

Units are **arc-seconds**, not `0.01 degree`: `GET_RES` returns 3600 on both axes, which
is exactly one degree per step. The advertised range is therefore ±150° pan, ±90° tilt.

The guarded physical test is a separate binary and must be run one axis at a
time only after confirming the camera is physically safe to move:

```sh
tools/pixy-probe/build/pixy-ptz-test pan 3000
tools/pixy-probe/build/pixy-ptz-test tilt 3000
tools/pixy-probe/build/pixy-ptz-test privacy
```

`pan` and `tilt` re-identify VID/PID and product strings, read the standard
PTZ state/ranges, write one positive advertised step, read it back, restore
the exact original coordinate, verify restoration, and close libusb handles.
They do not access HID, zoom, or focus. `privacy` is read-only and refuses to
write when the camera's advertised boolean values are outside `0`/`1`.
