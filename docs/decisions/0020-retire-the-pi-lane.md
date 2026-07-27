# Decision 0020: retire the Pi lane

**Status:** DONE. **Authority:** [2026] VJS-PC 20, L1 (and its conditions L2, L3).
**Occasion:** a Principal direction, 2026-07-27: "pi sidecar should be gone, we are
codex now."

## What was removed

The whole Pi lane: `services/pi_sidecar/` (the standalone reasoning gateway),
`boltrig/fleet/pi_runtime.py` (`PiRuntime`), the `pi` entry in
`_LEGACY_RUNTIME_KINDS` and its `_build_legacy_runtime` branch, the `pi_config`
plumbing through `build_runtime` and `RuntimeResolver`, the `pi-sidecar` compose
service in the base and release manifests, its release/security image matrices and
digest variable, its Dependabot ecosystems, and its lock audit.

## What it was doing

Measured before removal, across both production tenants:

| fact | value |
| --- | --- |
| `BOLTRIG_ENABLE_LEGACY_RUNTIMES` | unset on both stacks, so nothing could route to it |
| real `POST /run` requests, 6 - 27 July | **1** (on 2026-07-06) |
| health probes over the same period | 61,212 |
| credentials held | `PI_SIDECAR_TOKEN`, live |
| container state | `Up 8 days (healthy)` |

A service that cannot be reached by configuration, serves one request in three
weeks, and holds a live bearer is attack surface with no compensating value.

## The authority, and why it is not the direction

This is a scope fork, so it went to the citator, and the citator disposed of it.
[2026] VJS-PC 20 L1 permits "retiring opencode, herdr, mastra and **pi** from the
active roster", on the ratio that the safety property of VJS-CC-VJS 8 is carried by
**who forks the cell**, not by which binary it runs or how many vendors are wired.
A binding ratio on all fours is followed, not re-litigated (SPEC-LAW S-11(c)), so no
fresh convening.

Ashcombe PJ's doctrine in that judgment is the reason this section exists: an
executive re-direction by the Principal is **not of itself a lawful ground** to move
a holding. It triggers the court; the authority stays the court's. So the ground
recorded here, per **L2**, is **consolidation and reduced attack surface**, on the
measurement above. It is expressly **not** the "Boltrig is a thin wrapper around
Codex" intuition, which VJS-CC-VJS 8 rejected and PC-20 did not revive.

## Discharging L3, which is the condition that binds

> retain the manifest's multi-runtime ROUTING MECHANISM as live code, and keep at
> least one non-Codex governed leaf buildable and re-wirable by configuration
> alone, without a fresh order, as a quarantine fallback, until `production_ready`
> is unblocked.

Removing that mechanism is on PC-20's forbidden list. It stays, and five non-Codex
lanes remain re-wirable by setting `BOLTRIG_ENABLE_LEGACY_RUNTIMES` alone: `hermes`,
`openai`, `claude-api`, `opencode`, `rivet`. This is asserted rather than asserted
in prose, by `test_the_multi_runtime_routing_seam_stays_live`
(`tests/security/test_legacy_runtime_gate.py`), bound to **FR-RUN-21**: it fails if
the roster is emptied, and it constructs a lane rather than merely reading a list.

`production_ready` is untouched and stays False.

## Gated is not retired

A gated lane returns by setting one environment variable. A retired one does not
return at all. Both land on the same typed `UnavailableRuntime`, so a stored
capability, an `ai_config` or a tenant manifest still naming `pi` **degrades exactly
as it did while gated** rather than crashing (P9), reached by the unknown-kind
fallback instead of the legacy gate. No deploy changes behaviour on the day the lane
is deleted. `test_the_opt_in_flag_does_not_bring_pi_back` is the case that
distinguishes the two, and without it a test of the flag-unset path alone would pass
identically whether the lane was deleted or merely gated.

## What the deletion nearly took with it

Five invariants named Pi. Only two were about Pi. The rest are recorded here because
the pattern generalises: **a test's home should be the property it proves, never the
ticket that introduced it.**

- **IAC-003** (Trivy pinned, offline, blocking, exceptions expiring) had exactly one
  binding, and it lived in `tests/deploy/test_pi_dependency_lock.py` purely because
  that is where it was written. Deleting the file would have deleted the invariant.
  Moved to `tests/deploy/test_iac_scan_policy.py`.
- **SEC-48** was named `test_pi_sidecar_egress_is_enforced_in_manifests` and is the
  only assertion anywhere that the `sandbox` network is `internal: true` in the
  secure overlay and that postgres is unreachable from it. Re-pointed at
  `channel-gateway` and **widened** to every sandbox-confined service, so the next
  sidecar is covered on the day it is added.
- **FR-RUN-03** ("a Pi run's tool call passes the chokepoint") never touched
  `PiRuntime`: it issues a run-scoped token and asserts the kernel denies an
  out-of-scope verb. Moved to `tests/security/test_mcp_face.py`.
- **SEC-27** and **SEC-28** keep their properties through their OpenCode and
  channel-gateway bindings; only Pi's name and binding went.
- **FR-RUN-01** inverted rather than died: it asserted that a `pi` capability
  resolves to `PiRuntime`, and it now asserts the retirement itself.

Nothing here was caught by care. `scripts/check_invariants.py` reported nine
catalogue-drift rows and failed the moment the test files were deleted, which is the
whole reason the gate exists.

## One thing the deletion did shrink, stated rather than absorbed

**SEC-72** claimed that untrusted input is enveloped "at every composition site",
naming external tool results first. The only site that fed a tool result back into a
prompt was the sidecar's run loop, and no in-package site does it today: the Codex
runtime owns its own loop and nothing under `boltrig/` calls
`wrap_untrusted("tool_result", ...)`. The primitive is still bound, including its
breakout and delimiter-forgery cases; the SITE is not. SEC-72's description now says
so instead of continuing to claim a site that does not exist. Whether the Codex lane
needs its own envelope at that boundary is a separate question and is not decided
here.

## The tenant-side consequence, and the new check it earned

A tenant manifest outlives the image that served it. Measured on the Classical Visas
tenant on the day of the retirement: `runtimes.pi.enabled: true`, pointing at
`http://pi-sidecar:8090`, a service that no longer exists. Nothing anywhere reported
it.

`boltrig/api/doctor.py` used to check the sidecar's URL, bearer and egress
allow-list. Those checks went with the lane; what replaces them is a check for the
drift the retirement actually creates: a manifest still ENABLING a retired runtime.
It is a `warn`, never a deploy blocker, because such a capability degrades rather
than failing.

## What was corrected in my own reasoning

The plan for this change asserted that the deployed base compose would resurrect the
sidecar on the next `compose up -d`. It would not: the service carries
`profiles: ["legacy"]`, so it starts only when that profile is passed explicitly, and
no tenant script passes it. The container had been started by hand at some point and
`restart: unless-stopped` kept it alive for eight days afterwards. The removal was
still worth making durable, and the token still worth revoking, but the urgency was
overstated and the record should say that rather than quietly carry it.
