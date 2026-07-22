# 0016 - desktop hands: governed window control via a registry + authenticated HTTP pull (DH-1)

Status: accepted (2026-07-21)

## Context

The desktop familiar (decisions 0013/0014) needs HANDS, not just a face: list, focus, move and
arrange windows, switch workspaces, launch apps on the host desktop. These are ACTIONS, so they must
go through the one kernel chokepoint as real verbs with bindings, grant checks and audit rows (the
WL-3 ruling generalised). The complication is physical: the kernel runs in a container that cannot
reach the user's compositor IPC socket (Hyprland), so a granted dispatch cannot execute the window
action in-band the way `familiar.express` writes its little channel file.

DH-1 is the resulting invariant: desktop control goes through the chokepoint with no side door. The
only way a window action may reach the host is a granted, schema-bound, audited `desktop.*` dispatch
that a host-side executor claims over an authenticated pull surface.

## Decision

Three parts, one hand-off point:

1. `boltrig/kernel/hands_registry.py` - an in-memory `HandsRegistry` of pending commands, created
   ONCE in bootstrap and hung on the kernel, shared by the adapter and the routes. A command is
   `{id, verb, args, run_id, queued_at, claimed}`; claiming is mark-on-read so a polled command can
   never be double-executed; commands expire after 30 s unclaimed/uncompleted (swept lazily), so a
   stale window action can never be executed late.
2. `boltrig/adapters/builtin/desktop.py` - a normal builtin adapter (`desktop`, runtime `file`),
   same severability as `familiar.py` (imports only `adapters.base` + `models` + stdlib; the
   registry is injected). Every verb's handler enqueues a command and waits up to 8 s for the
   receipt. On receipt it returns `{status, delivered: true, result?, side_effects?, error?}`; on
   timeout `{status: "executor_offline", delivered: false}` - the governed act happened and is
   audited, delivery is best-effort (the decision-0014 doctrine).
3. `boltrig/kernel/desktop_routes.py` - the executor's pull surface, wired like `channel_routes`:
   `GET /v1/hands/commands` claims + returns pending commands, `POST
   /v1/hands/commands/{cmd_id}/receipt` resolves the waiting dispatch (404 for unknown/expired ids).
   Both require the normal authenticated principal (SEC-01); every receipt is audited as
   `desktop.hands.receipt` (SEC-16) so the host-side execution is kernel-recorded next to the
   dispatch that authorised it.

The verb/risk table:

| verb | args | consequence | rate limit | idempotency |
| ---- | ---- | ----------- | ---------- | ----------- |
| `desktop.window.list` | `{}` | low | 120/min/tenant | cacheable |
| `desktop.window.focus` | `{address}` | low | 60/min/tenant | disabled |
| `desktop.window.move` | `{address, x, y, width, height}` | HIGH | 60/min/tenant | disabled |
| `desktop.window.arrange` | `{placements[], preview?}` | HIGH | 60/min/tenant | disabled |
| `desktop.workspace.switch` | `{workspace}` | low | 60/min/tenant | disabled |
| `desktop.app.launch` | `{exec}` | HIGH | 60/min/tenant | disabled |

Schemas are fully bound (`additionalProperties: false` everywhere, positive width/height, ranged
workspaces, bounded placements/exec) so the binding rejects garbage before the handler runs
(SEC-21). HIGH-consequence verbs are HITL-gated by the existing consequence gate (SEC-14): moving
windows and launching apps ask a human first, reading and focusing do not.

Idempotency reasoning: `cacheable` means a retry with the same key is served the STORED result
without re-executing. That is fine for `window.list`, a pure read. It is not fine for anything that
changes host state: a replayed receipt would claim `delivered: true` for a delivery that did not
happen, and desktop state is too ephemeral for a cached execution record to mean anything. So every
state-changing verb is `disabled` - a retry must re-enter the chokepoint as a fresh granted, audited
dispatch. (Focus and workspace.switch are low-consequence, but they still move the user's screen, so
they get `disabled` too.)

## Consequences

- DH-1 is bound by `tests/security/test_desktop_hands.py`: granted dispatch queues + audits; an
  ungranted call is denied + audited and queues NOTHING (no side door); bad geometry is
  schema-rejected before the handler; a claimed command cannot be claimed twice; a receipt resolves
  the waiting dispatch; an absent executor yields `executor_offline` with the audit row standing.
- The host executor (beelink-desktop side) is out of scope here. Its contract: poll
  `GET /v1/hands/commands` with its principal, execute each claimed command within 30 s, POST the
  receipt `{status: "ok"|"error", result?, side_effects?, error?}`. Claimed means owned: a command
  appears in exactly one poll response.
- The registry is kernel-global, not tenant-scoped: the deployment model is one kernel serving one
  desktop host (the beelink). A multi-tenant deployment would need tenant partitioning on the pull
  surface; recorded here as a known limit, not built.
- Manifest boots register the verbs only where the familiar lives (`BOLTRIG_EMOTION=1`, the
  desktop-only flag); the manifest-less demo seed registers them for the default tenant.
- Amendment (2026-07-21): the add-on is OPT-IN, not boot-default. Registration of both the verbs
  and the shared registry now requires `BOLTRIG_DESKTOP_HANDS=1` on every boot path (seed and
  manifest, the latter independent of the emotion flag). A kernel that does not drive a desktop
  must not even advertise the capability: no adapter, no verbs, `/v1/hands/*` answers
  `hands_unavailable`. The operator opt-in and the host-side executor install are the two halves
  of "the add-on is turned on and installed"; `test_desktop_verbs_only_exist_when_the_addon_is_enabled`
  binds this.

## Alternatives rejected

- Writing command files into the shared `/tmp/boltrig-rt` bridge: any local process can write there,
  so a "command" is forgeable. The express channel tolerates this because it is content-free (a
  closed gesture enum + two numbers, worst case a cosmetic lie on the surface). Window control is
  not content-free: a forged move/launch is a real, un-audited action. Commands must come from a
  granted dispatch, which only the in-kernel registry can guarantee.
- Bind-mounting the compositor socket into the kernel container: breaks container isolation for the
  strongest capability on the box (arbitrary window control + arbitrary exec), and couples the
  container to one user's session lifecycle (socket paths, env, session restarts). The pull model
  keeps the host capability OUTSIDE the container and puts an authenticated, audited seam in front.
- A host-side push listener the kernel calls outbound: inverts the trust direction (the container
  would need a reachable host endpoint + credentials to it) and loses the claim-on-read
  exactly-once semantics the registry gives for free.
