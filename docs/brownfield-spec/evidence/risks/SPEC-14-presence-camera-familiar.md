# Risks harvested from SPEC-14-presence-camera-familiar.md

RISK: `GET /v1/familiar/phenotype` claims to be owner-scoped but ignores the
principal entirely and returns a PROCESS-WIDE file, so any authenticated
principal of any tenant reads whichever tenant's mood the publisher last wrote.
[`boltrig/kernel/familiar_phenotype_routes.py:82`](../../../boltrig/kernel/familiar_phenotype_routes.py)
`"async def familiar_phenotype(p=principal):"` with `p` unused, against the
docstring at line 83 `"Owner-scoped, cosmetic, read-only"`. EMO-4 scopes the
ENGINES, not the published file.

---

RISK: the emotion publisher only ever publishes ONE tenant's phenotype, chosen as
the engine named `"default"` or, failing that, the single engine when exactly one
exists. A two-tenant process where neither is `"default"` publishes nothing at
all, silently. [`boltrig/emotion/relay.py:303`](../../../boltrig/emotion/relay.py)
`"engine = self._engines.get(self._tenant)"`.

---

RISK: no invariant in `tests/invariants.yaml` binds the camera lease plane or the
sensing consent surface, although both are security-relevant and both carry a
consumed-approval and a consent gate. The camera plane is the exact shape
`SEC-WRK-07` binds for devices. Bounded: `grep -n -i "camera\|sensing" tests/invariants.yaml`,
2026-08-24, one hit, about CSP.

---

RISK: `camera.ptz.get` and `camera.ptz.set` are declared
`idempotency_mode: "cacheable"` ([`boltrig/adapters/builtin/camera_leases.py:32`](../../../boltrig/adapters/builtin/camera_leases.py)
`""idempotency_mode": "cacheable","`), while decision 0016's stated reasoning
for the sibling desktop verbs is that a replayed receipt claiming a delivery that
did not happen is unacceptable for anything that changes host state
([`docs/decisions/0016-desktop-hands.md:56`](../../../docs/decisions/0016-desktop-hands.md)
`"Idempotency reasoning: `cacheable` means a retry"`). A cached `camera.ptz.set`
result returns a lease id whose lease may already be settled or expired.

---

RISK: the shipped `descriptor_fingerprint` is a hash of USB TOPOLOGY
(`vid:pid:bus:port.path`), not of the descriptor
([`apps/worker/src-tauri/src/camera_uvc.m:202`](../../../apps/worker/src-tauri/src/camera_uvc.m)
`""%04x:%04x:%u:", vendor, product,"`). The field name asserts a property the
value does not have: it changes when the camera is replugged elsewhere and does
NOT change when the device's descriptors change. `boltrig/camera/discovery.py`
computes the descriptor-shaped one, and that module is unwired.

---

RISK: `boltrig/camera/` (7 modules, 1165 lines) and
`boltrig/adapters/builtin/camera.py` (128 lines, four verbs including
`camera.snapshot`) are reachable only from tests. Two classes named
`id = "camera"` exist; registering both on one tenant would collide. Bounded
search stated in section 4.4.

---

RISK: `docs/DESIGN-familiar-in-boltrig.md` describes a genotype derived from a
ROLE (orchestrator, researcher, reviewer, builder, guardian, analyst) rendered
through `ui/src/panels/chat/AgentAvatar.tsx`. Neither exists: the shipped
derivation is a sha256 over the capability name selecting one of four astronomy
bodies ([`boltrig/models/familiar.py:62`](../../../boltrig/models/familiar.py)
`"body=_BODIES[digest[0] % len(_BODIES)],"`), and there is no `ui/` directory in
the pinned tree. The document carries no status header saying it is superseded.

---

RISK: `presence = 'locked'` is a legal value of the `devices` CHECK constraint
and of the SDK's `DevicePresence` union, and nothing in the tree ever writes it.
Bounded: `rg -n "'locked'|\"locked\"" boltrig/ apps/worker/src-tauri/src/ sdks/ tests/`,
2026-08-24, hits only the enum declarations. `offline` is likewise write-once at
creation and never restored. A UI reading `presence` cannot distinguish a device
that has gone away from one that is online.

---

RISK: `availability_mode` is projected to owners and rendered in the Worker
device list, yet its CHECK admits exactly one value
([`migrations/versions/0042_desktop_devices.py:40`](../../../migrations/versions/0042_desktop_devices.py)
`"CHECK (availability_mode IN ('unlocked_session'))"`). It is a field that cannot
carry information.

---

RISK: the hands registry is kernel-global rather than tenant scoped, so on a
multi-tenant deployment any authenticated principal polling `/v1/hands/commands`
claims commands queued by any tenant. Decision 0016 records this as a known
limit ([`docs/decisions/0016-desktop-hands.md:74`](../../../docs/decisions/0016-desktop-hands.md)
`"The registry is kernel-global, not tenant-scoped"`), and
[`boltrig/kernel/desktop_routes.py:61`](../../../boltrig/kernel/desktop_routes.py)
`"for cmd in reg.pending():"` confirms no tenant filter.

---

RISK: `GET /v1/sensing/capability` cannot enforce declaration and the module says
so at length, but the route is what a client naturally reads as the enforcement
point. The Stage constraint that limits asks to `wantsSensing` is not a boundary,
because a character add-in shares the Worker's JavaScript realm and can call
`client.sensingCapability` for anything
([`boltrig/kernel/sensing_capability.py:35`](../../../boltrig/kernel/sensing_capability.py)
`"the Stage and NOT a security boundary"`).

---

RISK: `signer_for` falls back to reading the environment on EVERY request when
`app.state.device_lease_signer` is unset
([`boltrig/kernel/device_route_support.py:28`](../../../boltrig/kernel/device_route_support.py)
`"DeviceLeaseSigner.from_environment()"`, reached by the `or` on the line above),
so an env change mid-process
silently changes the signing identity between two requests of one flow.

---

RISK: `boltrig/api/bootstrap.py` registers `familiar.express` unconditionally on
the demo seed path ([`boltrig/api/bootstrap.py:119`](../../../boltrig/api/bootstrap.py)
`"build_familiar())  # familiar.express (WL-3)"`) but only when
`BOLTRIG_EMOTION == "1"` on the manifest path (line 289). The two boot paths
disagree about whether the verb exists, and neither is gated on the express
channel actually being readable.

---

RISK: `scripts/check_familiar_shader.sh` compares the vendored copy against a
path outside the repository, while an identical canonical copy now exists inside
it at `familiar/familiar.frag`. The in-repo vitest covers that pair; the shell
script's external comparison exits 2 on the machines that lack the checkout, so
its green is unavailable in CI by construction.

---

RISK: `camera_bindings` rows have no delete route and no expiry. The runbook
records this as an accepted orphan
([`docs/ACTIVATE-SENSING-RUNBOOK.md:152`](../../../docs/ACTIVATE-SENSING-RUNBOOK.md)
`"The row stays, orphaned and inert"`), which means a revoked device's bindings
persist until the CASCADE fires on the `devices` row.

---

RISK: `libraries/emotion/event_map.yaml` carries the same two-line comment about
adoption twice, once at lines 34 to 35 and again at 37 to 38, with the rule
itself only after the second copy. It is cosmetic, but it is the shape of a bad
merge in a data file that changes runtime behaviour with no code review gate.
