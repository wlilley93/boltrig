# Camera profiles

Profiles are declarative local metadata. They may match USB identity, improve
labels, describe standard-protocol quirks, and name a separately trusted
implementation. They never contain commands, scripts, URLs, modules, or raw
HID reports. A profile match is not proof of a capability; current-device
evidence still controls the capability state.

The EMEET Pixy profile is fixture #1. Its standard PTZ route is UVC. The HID
and privacy paths remain inactive until separately proven by explicit tests.

The profile loader requires an explicit trusted-id set before vendor metadata
is active. The repository profile is therefore safe to inspect and match by
default, but it cannot activate a vendor implementation on its own.
