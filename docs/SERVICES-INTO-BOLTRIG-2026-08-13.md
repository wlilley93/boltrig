# Camera and presence as first-class Boltrig services

**Date:** 2026-08-13
**Box:** M4 (`mac-mini-m4-pro`) only. No new listener, no rebind, no tailscale
change, no presence bridge to beelink.
**Phase:** 3 of `~/.claude/plans/swirling-zooming-sundae.md`.
**Status:** kernel half built and verified. **Host half now wired and
adversarially verified (§12) — but not in effect**, because the deployed kernel
serves no sensing route and no device credential exists on this box (§13).
Uncommitted, awaiting review. Nothing was restarted.

This document is written from a verification pass, not from the build report.
Every number below was produced by a command run in this session; where something
could not be proven, it says so rather than rounding up.

---

## 1. What actually moved

The governing decision — *the daemon is always Boltrig's, whoever is watching* —
is now true of **configuration and consent**. It is not yet true of the
**processes**.

| thing | before | now |
| --- | --- | --- |
| camera on/off, device, retention, quiet hours | constants in a companion repo | kernel `user_settings`, `sensing.*` |
| the enrolled face | `~/pixy-stream/identity/enrolled.npz` | kernel record (metadata only) — file still on disk |
| "may I see?" | never asked | `GET /v1/sensing/capability`, answered with a reason |
| the capture thresholds | `capture_policy.py` | mirrored in the kernel — **nothing reads them yet** |
| camerad / presence / capture processes | `app.pixy.*`, `app.companion.*` | **unchanged, still independent** |

The important line in that table is the last one. See §6.

---

## 2. Kernel schema

Settings live in the existing `user_settings` table, following
`agentic.approval_posture` exactly rather than inventing a table beside it.

```
sensing.camera.enabled           bool                       default false
sensing.camera.binding           {device_id, camera_id, descriptor_fingerprint} | null
sensing.camera.retention_hours   int                        default 24
sensing.camera.quiet_hours       {start, end}               default {22, 8}
sensing.presence.enabled         bool                       default false
sensing.enrollment               {digest, threshold, count, far_measured, basis} | null
```

Both defaults are off. A fresh Boltrig watches nothing until someone says so in
a UI — verified: a fresh kernel returns
`{"enabled": false, "source": "safe_default", "binding": null, ...}`.

`source` distinguishes *off because you decided* from *off because nobody has*,
which is what stops the UI presenting a default as a choice.

### The deviation from the design — stated plainly

The design called for a `sensing_enrollments` table with `vectors BYTEA`,
`threshold NOT NULL` and `CHECK (exportable = false)`, in migration
`0074_sensing_enrollment.py`.

**That migration does not exist.** Verified: `migrations/versions/` ends at
`0073_agent_model_routes.py`, and `sensing` appears nowhere in
`boltrig/store/schema.sql` or `rls.sql`.

The enrolment is instead a `user_settings` row holding **metadata only** —
digest, threshold, count, `far_measured` — never the vectors. The build report
disclosed this and gave a reason (`boltrig-vm` stopped, so the migration could
not be run). **That reason no longer holds:** `orb list` shows `boltrig-vm
running`, and Postgres on `127.0.0.1:5432` answers a real handshake (it rejected
my credentials with `InvalidPasswordError`, which only a live server does). I
could not run the migration myself because I do not hold the DB password — the
kernel owns it.

What survives the deviation: the threshold has no fallback, so `parse_enrollment`
returns `None` without one and presence cannot be enabled. What is lost: that is
a **parser invariant, not a schema invariant**. A future writer who bypasses the
parser is not stopped by the database. Whoever has the DB password should promote
it.

---

## 3. The refusal contract

`SensingRefusal` is a `StrEnum` of eleven reason codes shared by kernel, daemons
and UI. `camerad_holds_device` is the string `camera_uvc.m` already speaks,
reused verbatim rather than given a synonym.

> **Superseded in part by §11.** `capability_not_declared` was removed and
> unknown names now answer `capability_unknown`; the Worker adds one code the
> kernel cannot emit, `kernel_unreachable`. The enum is still eleven members.

Wire shape, **409 not 403** — the user is permitted and chose off; 403 would say
"you may not", which is untrue:

```json
{"status": "refused", "capability": "camera_observations",
 "reason": "camera_disabled",
 "detail": "The camera is turned off in Settings › Camera and presence.",
 "remedy": "settings:sensing"}
```

`"refused"`, never `"error"`. A user who turned the camera off got what they
asked for; that is a correct answer, not a fault. This is the deliberate opposite
of `familiar_phenotype_routes`, which answers *resting* on failure because a
cosmetic side-channel must not read as a fault. Sensing must be **visible**.

### Verified against the running code

With the camera off, a character asking:

```
camera_observations -> HTTP 409  reason=camera_disabled   + detail + remedy
presence            -> HTTP 409  reason=camera_disabled   + detail + remedy
```

- No crash, no exception, no empty 200.
- **No substitution:** the refusal body carries no `frame`, `observation`,
  `image`, `cached` or `fallback` key. Checked by key inspection, not by eye.
- A garbage capability name (`../../etc/passwd`) returns a named refusal, not a
  stack trace. (It answered `capability_not_declared` when this was written;
  `capability_unknown` since §11.)
- Presence is checked **after** the camera deliberately: with the camera off,
  "presence is disabled" would be true but would hide the reason that applies.
- **The bypass is closed.** `PUT /v1/me/settings` with the raw key
  `sensing.camera.enabled` returns `400 {"reason": "use the sensing endpoints"}`
  and the camera stays off. A validated route reachable by its raw key is not
  validated.
- Every mutating route requires an interactive human session — a delegated agent,
  or a character, cannot turn your camera on.

Worker side (`StageBody.tsx:93`) fails toward refusal: a kernel that cannot be
reached yields a refusal, never a grant, and the decision is re-asked every 30 s
so a toggle bites within the capture interval rather than at restart. A character
declaring nothing costs no request.

---

## 4. The enrolled face

Anchor images are the *character's* face and travel with a bundle. The enrolled
face is the *user's*, and a character is a thing you might share.

The projection reports `present`, `count`, `threshold`, `far_measured` and a
constant `"exportable": false` — never anything that could reconstruct a face.
The export side is structural: the enrolled face has **no field in the manifest
schema at all**, so it is not a filter that must be remembered but a shape that
cannot carry it. `far_measured: false` is surfaced so the UI can say honestly that
the false-accept rate was never measured.

**Not done:** `~/pixy-stream/identity/enrolled.npz` and its two
`.bak-20260813-*` copies are still on disk. Nothing has migrated or deleted them.

---

## 5. Network posture — verified, unchanged

`lsof -nP -iTCP -sTCP:LISTEN` this session:

- camerad (PID 62465) holds `127.0.0.1:8896`, `:8899`, `:8900` — loopback, as before.
- pocket-voice `127.0.0.1:8911`, pocket-ears `127.0.0.1:8912` — loopback, as before.
- **No listener attributable to this phase.** The sensing code contains no
  `bind`, `listen`, `socket`, `uvicorn`, `0.0.0.0`, or HTTP-client call; it is
  routes registered on the kernel app that already exists.

`tailscale serve status` is unchanged by this work, and no serve/plist/infra file
is modified in the tree. For the record, the existing mounts are
`:8443 → 11434`, `:8444 → 8896`, `:8898 → 8898`, `:8933 → 5173`.

> **Pre-existing, flagged not fixed:** `:8444` proxies camerad's `127.0.0.1:8896`
> onto the tailnet. It answers `HTTP 401`, so it is token-gated, and it predates
> this phase. It is named here because a camera-adjacent port on the tailnet
> deserves a deliberate decision rather than silence.

No presence bridge to beelink was built or prepared.

---

## 6. The launchd jobs are NOT driven by kernel settings

> **SUPERSEDED 2026-08-13 22:52 by §12.** The host half is now written and
> proven. This section is kept because it states the defect the fix answers, and
> because its last paragraph is still true of the *running* processes: the live
> daemons below have not been restarted and are executing the pre-edit code.

Verified by `launchctl list`:

```
62465  app.pixy.camerad        <- still running, still independent
61949  app.pixy.presence       <- still running, still independent
32758  app.companion.observer  <- still running, still independent
83524  app.companion.vigil     <- untouched, out of scope
```

Still named `app.pixy.*` / `app.companion.*`, not `app.boltrig.*`. Their plists
date from Aug 11–13, before this phase.

**Nothing on the host reads the kernel.** A grep for `sensing` across
`~/Projects/companion-observer/*.py` and `~/pixy-stream/*.py` returns nothing.
`capture_policy.py` still holds its own constants (`THUMB = 64`, `INTERVAL = 30`,
`GESTURE_PAUSE_S = 1800`, `RETENTION_H = 24`) as live values, not as fail-safe
defaults behind `sensing-config`.

The kernel's `CAPTURE_THRESHOLDS` mirrors those numbers exactly, so the contract
is agreed — but it is a contract with no client.

**Consequence, stated so nobody is misled:** switching the camera off in the
Worker UI today changes what a *character is told*, and does **not** stop
camerad, capture or presence. The consent surface is real; the enforcement at the
hardware is not yet wired. Closing that is the next piece of work, and it lives
in `~/Projects/companion-observer` and `~/pixy-stream`, outside this tree.

---

## 7. The camerad interlock — read, not assumed

`apps/worker/src-tauri/src/camera_uvc.m` has **zero diff** against HEAD.
`CameradHoldsDevice()` still ends:

```objc
// Only these mean the device is genuinely free.
return !([status isEqualToString:@"stopped"] || [status isEqualToString:@"idle"]);
```

It fails **closed**: any status other than those two means do not touch the
camera; JSON that does not parse is treated as an owner (`unparseable`); only a
timeout or non-200 is treated as "not holding", because camerad not running is
the common case. `CaptureOneFrame` returns
`{ok: NO, capture_attempted: NO, blocked_by: "camerad"}` — it does not attempt a
second `AVCaptureSession`.

Live confirmation: `curl 127.0.0.1:8899/healthz` returns `{"status": "live"}`,
which is precisely an input the interlock treats as holding the device.

Behaviour preserved exactly. Recovery from a wedged UVC device is a physical
replug, and nothing here risks one.

---

## 8. Gates — real numbers from this session

```
apps/worker $ node_modules/.bin/tsc --noEmit -p tsconfig.json
exit 0, zero output

apps/worker $ node_modules/.bin/vitest run
Test Files  86 passed (86)
     Tests  788 passed (788)
exit 0

$ .venv/bin/python -m pytest tests/security/test_sensing_settings.py -q
10 passed
```

**Correction to the build report.** It reported one failure,
`apps/worker/tests/visual/manifest.test.ts`. That test now passes (22/22 alone, and inside
the full green run). The reason is not that anything was fixed here: the VDS
ledgers `.vds/ledgers/{routes,screens}.yaml` were rewritten at **21:50:57** by a
concurrent session — after this phase's files were written (21:38–21:46) and
seconds before my run. That regeneration baked another session's mid-edit
`VoiceCall.tsx` digests into the ledger, which is exactly what the build agent
declined to do. The suite is green; one should know *why* it went green.

`scripts/check_vds_ledgers.py` could not be run under the system python
(`ModuleNotFoundError: yaml`); it needs `.venv`.

---

## 9. Not done

- The `0074` migration and the `sensing_enrollments` table (§2). The stated
  blocker no longer holds.
- ~~The host daemons are not wired to the kernel~~ — **done, see §12.** The
  launchd jobs are still unrenamed, and still *running the pre-edit code*: the
  gate takes effect on restart, and restart is blocked on §13.
- `enrolled.npz` and its two backups are still on disk (§4).
- Observations (`observations.jsonl` + JPEGs) remain host-side, as the design
  recommended deferring.
- The full Python suite was **not** re-run in this pass — only the sensing
  security file. The build report's figure of 3065 passed / 2 failed is
  unverified here.
- No commit was made.

## 10. Two defects found in review

1. **`StageBody.tsx:106` misstates a reason code.** When the kernel cannot be
   reached the fallback sets `reason: "camera_disabled"`, but the detail says
   *"could not be reached"*. The prose is honest; the machine-readable code is
   not — it reports a user choice where the truth is an unreachable kernel. In a
   phase whose whole subject is honest refusal, that code should be its own
   reason (e.g. `sensing_unreachable`). Behaviour is safe either way: it fails
   toward refusal.

2. **The kernel cannot enforce declaration.** `GET /v1/sensing/capability` sets
   `declared=capability in CAPABILITIES` — i.e. "is this a known capability
   name", not "did *this character's* bundle ask for it". The kernel has no idea
   which character is calling. So `capability_not_declared` can only ever fire
   for an unknown name, and a character that declared nothing can still ask and,
   with the camera on, be told `granted`. Declaration is enforced Worker-side
   (`wantsSensing`) only. The endpoint returns a decision and never pixels, so
   this leaks no imagery — but it is weaker than the spec's "a character
   DECLARES and is refused" reads, and should be written down rather than
   assumed.

## 11. What was done about them, later the same day

### Defect 1 — fixed

The unreachable case has its own code. `StageBody.useSensing` now synthesises

```json
{"status": "refused", "capability": "camera_observations",
 "reason": "kernel_unreachable",
 "detail": "Boltrig could not be asked, so consent is unknown and nothing is being seen.",
 "remedy": "retry:automatic"}
```

Both paths that could not ask — a failed request, and a client too old to know
the route — use it, because both mean the same thing: the question was never
put. It still **fails toward refusal**, and the 30 s re-ask is unchanged, so the
real answer lands within one capture interval of the kernel coming back.

`kernel_unreachable` is the one reason code in `SensingRefusalReason` the kernel
**cannot** emit — a kernel that answers is by definition reachable — and it is
absent from the Python `SensingRefusal` enum for exactly that reason. `remedy`
gained `retry:automatic` alongside `settings:sensing`: there is nowhere for the
user to go, and pointing them at Settings would be the same lie in a different
field.

### Defect 2 — NOT faked; the limitation is now stated in the code

Enforcement was **not** implemented, and nothing pretends it was. What it would
need, established by reading rather than guessed:

- `Principal` (`kernel/app.py`) carries tenant, subject, grants, role, tier,
  credential kind, workspace, ip/ua — **nothing naming a character**.
- There is **no kernel-side record of installed bundles** at all: no table in
  `store/schema.sql`, no model, nothing. A declaration check has nothing to
  check against, so it needs a table and a migration — and `0074` for
  `sensing_enrollments` (§2) is *still* outstanding ahead of it.
- Threading a character id onto `Principal` would have to follow the
  `active_workspace_id` rule: re-authorised every request, **never read from the
  request body**. There is no membership to re-authorise against until the
  record above exists.
- And the part that is not plumbing: the caller is browser JS. A character
  add-in shares the Worker's JavaScript realm with every other character, so a
  self-declared id proves nothing and a kernel-minted one is readable by its
  neighbours. This is unresolved by design work, not by a schema.

That is a schema *and* an identity change, larger than this pass. So instead:

- `capability_not_declared` is **removed** from the wire, the Python enum and
  the SDK union. It fired for any unknown name while claiming a character had
  not declared something — an enforcement no layer performs.
- Unknown names now answer **`capability_unknown`** ("This Boltrig has no such
  capability to give"), with **no `remedy`**, because no switch in Settings
  grows a capability.
- `capability_decision` lost its `declared` keyword. Its only caller passed
  `capability in CAPABILITIES`, which dressed a name check as a declaration
  check.
- The limitation is written out in the module docstring of
  `kernel/sensing_capability.py`, on the `GET /v1/sensing/capability` handler,
  on the `SensingRefusal` enum, and next to `SensingRefusalReason` in the SDK.
- `test_the_kernel_does_not_know_which_character_is_asking` pins it as
  behaviour: a caller claiming `&character=…` gets a byte-identical decision.

**Standing truth until that work is done:** the kernel governs *consent*, not
*declaration*. An undeclared character asking with the camera on is told
`granted`. No imagery leaks either way — the endpoint returns a decision and
never a frame, and capture is gated on the user's switch rather than on who
asked.

---

## 12. The host half — wired, and verified adversarially

§6 said the switch changed *what a character was told* and did not stop the
camera. That is now closed in code. This section is the evidence, not the claim:
every number came from a command run in this session, and where a thing was not
observed it says so.

### What enforces it

One client, `~/Projects/companion-observer/capture_policy.py`, imported by all
three daemons — observe/capture (3.14), presence (pixy-stream's 3.11 venv) and
camerad (stdlib-only). `camera_gate()` / `presence_gate()` return a `Decision`
that is **falsy on refusal**, so `if not gate: stand_down()` cannot be got wrong
by forgetting to read a field.

Placement matters more than the check does:

| daemon | where the gate sits | what a refusal costs |
| --- | --- | --- |
| capture.py | **inside `grab()`, ahead of `shutil.copy`** | no grab, no archive, nothing to interpret |
| presence.py | **before `grab()`** | the snapshot is never *requested* |
| camerad.py | **`FrameBus.publish()`** — the single choke point | every consumer refused at once |

capture's gate is in `grab()` rather than in the loop deliberately: every route
to a frame in that module passes through it, so a caller added later is gated by
construction rather than by a reviewer noticing.

### Verified by running it

The deployed kernel has no sensing routes (§13), so the daemons were driven
against a stub on loopback speaking the designed contract, with a real
credential file and real token auth (wrong token → 401, wrong device → 401). The
processes were the **production files**, run as **real subprocesses** under the
same interpreters the plists use.

**The static-room confound was removed.** A frame feeder replaced camerad's
`current.jpg` with real archived frames on a 3s rotation; measured pairwise
change 10.1–30.4 against `CHANGE_THRESHOLD = 6.0`, mean luminance 97–107 against
`DARK_MEAN = 12.0`. So during every window below the loop had **no local reason
to skip a frame**. "Nothing was archived" can only mean the gate.

```
camera ON      12 frames archived, 12 observation rows, 10 diary lines
               written by the real VLM (mac-mini-m1 qwen3vl-abliterated);
               presence fetching a snapshot every 8s
```

```
camera OFF at 22:39:50.77
  observer   last frame archived      -7.62s  (BEFORE the flip)
             frames after the flip:    0      over 90s
             observation rows after:   0
             log: "[observe] standing down: camera_disabled"
  presence   last snapshot fetched    -1.38s  (BEFORE the flip)
             snapshots after:          0      over 90s
             stood down at            +6.63s
             bus event: {"stood_down": "camera_disabled", "known": false}
  both processes still alive -- a refusal is a pause, never an exit
```

The one number that needs saying plainly: **diary lines went 10 → 11 after the
flip.** That eleventh line is the interpretation of the frame archived at
22:39:43, *before* the camera was switched off — capture commits before any
character sees the frame, so an in-flight reading of a lawfully-captured frame
completes. No diary line describes any moment after the switch.

```
camera back ON at 22:42:06
  first frame archived      +0.58s      7 new frames in 60s
  first snapshot fetched   +15.29s      6 new snapshots
  diary 11 -> 16
```

### Fail-off — an unreachable kernel is never consent

The stub kernel was killed outright at 22:44:54. **Its last answer had been
`camera: enabled`.**

```
80s with no kernel at all:
  frames archived   0        snapshots fetched  0
  last frame archived  -7.92s (before the kill)
  "standing down: kernel_unreachable (<urlopen error [Errno 61] Connection refused>)"
  both daemons alive
```

Every refusal path was probed directly through the production module:

```
mode                          allowed  reason               remedy            detail
kernel serving camera=off       False   camera_disabled      settings:sensing
kernel up, route 404            False   kernel_unreachable   retry:automatic   HTTP 404 kernel has no sensing-config route
kernel up, body v:9             False   kernel_unreachable   retry:automatic   unknown config version 9
no credential file              False   kernel_unreachable   retry:automatic   no readable <path>
dead port                       False   kernel_unreachable   retry:automatic   Connection refused
THE REAL KERNEL, 127.0.0.1:18000  False kernel_unreachable   retry:automatic   HTTP 404 kernel has no sensing-config route
```

### The stale-ON bound is 10s, and the kernel can only shorten it

`CONFIG_TTL_S = 10`. The kernel's own `max_stale_s` is clamped with `min()`, so
it can shorten and never lengthen. Tested against a hostile value: with the
kernel serving `max_stale_s: 86400` and `camera: enabled`, then killed —

```
t=0.0s  cached a GRANT (max_stale_s served = 86400)
kernel KILLED
t=9.6s  REFUSED: kernel_unreachable
```

A day-long grant was honoured for 9.6 seconds. Worst case between a Settings
toggle and a stand-down is `CONFIG_TTL_S` plus the daemon's loop interval;
measured 6.6s for presence, under 8s for the observer.

### The stop gesture and quiet hours are not regressed

- `character.prose_suggests_stop` on the real 21:25 description — *"one arm
  extended and hand open towards the camera"* — returns **True**. The 18:04 line
  also returns True. Four negative controls all return False.
- `gesture_check()` is still asked on every archived frame, ahead of any
  character, and still returns a bool without raising; the loop still fails
  **closed** (`stop = True`) if it throws.
- The withdraw path still works: `capture.withdraw(obs)` removed the frame from
  disk and dropped its row (30 → 29 rows), leaving earlier rows intact.
- Archive-before-interpretation ordering is unchanged — it is what makes the
  in-flight diary line above correct rather than a leak.
- Kernel-supplied quiet hours bite: an early run granted consent at 22:18 and
  still captured nothing, because the window was 22:00–08:00.

### Network posture — unchanged, verified

The consent work adds **no listener**. Diffing every network-bearing line of
`camerad.py` and `presence.py` against their `.pre-sensing-*` backups produces
**empty output**: same three binds, all `127.0.0.1` (8896 viewer, 8899 read,
8900 write). The only new traffic is an **outbound** `urlopen` to loopback. No
rebind, no tailscale change. `lsof -nP -iTCP -sTCP:LISTEN` shows nothing
off-loopback that was not already there (rapportd, ARDAgent, ControlCenter,
tailscale, OrbStack, limactl).

### Two residual findings

1. **`GateLog` suppresses a changed cause.** It keys on `(allowed, reason)`, and
   all three host failures share `kernel_unreachable`. Watched live, a kernel
   that went from *connection refused* to *404 no route* kept printing the old
   `Connection refused` detail — the log line did not update, because the key had
   not changed. Safety is unaffected (both refuse); the operator-facing `detail`,
   which is the only thing distinguishing "start the kernel" from "deploy the
   kernel", can be stale. `detail` should take part in the key.

2. **A stale `current.jpg` survives a cold start with the camera off.**
   `consent_poller` deletes `current.jpg` only on a *transition* to refused, and
   the initial state is already refused — so `changed` is `False` and the cleanup
   branch is never taken. Demonstrated against a scratch copy. It is **not** a
   bypass: `publish()`, `/snapshot.jpg` and `/stream.mjpg` all refuse, and
   `grab()` gates before reading it. But an image of the room persists on disk
   while Settings says the camera is off, which is exactly the kind of thing this
   surface is judged on. The fix is to delete it on any refused poll, not only on
   the edge.

### What was NOT observed

**No stand-down on the live daemons.** `app.pixy.camerad` (62465),
`app.pixy.presence` (61949) and `app.companion.observer` (32758) ran the
pre-edit code throughout and were never restarted; the live camera stayed on and
`current.jpg` kept refreshing. camerad's standby was proven **in-process** —
`publish()` drops while refused, `discard()` clears the retained frame,
`latest()` returns `None`, `/health` reports `standby` while `wedged` still
outranks it — but a second camerad was deliberately **not** started, because it
would contend for the UVC device whose recovery is a physical replug.

**The consent gap is closed in code and not yet in effect.** It takes effect on
restart, at which point all three daemons stand down until §13 is resolved.

---

## 13. What still blocks turning it on

**Status at 2026-08-13 23:15. The bridge is STILL IN PLACE and the camera is
STILL ON.** `BOLTRIG_SENSING_UNMANAGED=1` remains in all three plists. Nothing
was retired, because the route it was waiting for still is not deployed.

### 13.1 The wiring is DONE; the IMAGE is stale

This is the correction that matters, because the previous note blamed the wrong
layer. `register_sensing_routes` **is** called in the tree —
`access_routes.py:187` → `account_profile_routes.py:203` — and
`camera_agent_routes.register_camera_agent_routes` registers both device-agent
sensing paths. Building `create_app` from the tree yields 249 paths including
all seven sensing routes. **No source change is needed.**

What is stale is the running container. Two independent confirmations:

    live openapi.json           230 paths, 0 matching "sensing"
    inside boltrig-kernel-1     grep -c sensing camera_agent_routes.py  ->  0

The second is decisive. The deployed copy of `camera_agent_routes.py` — the file
that registers `camera-bindings`, which *is* live — contains no occurrence of
the string `sensing` at all. Same registrar, same file: the neighbouring routes
answer and these two do not. So this is purely "the image predates the code",
not a wiring bug, and rebuilding the kernel image is the whole fix.

### 13.2 The route name in this doc and in capture_policy.py is WRONG

There is no `/v1/sensing/config` and there never was. The daemon path is:

    GET /v1/device-agent/{device_id}/sensing-config

`capture_policy.py:241` already calls the correct URL, so no daemon is broken by
this. But two of its own comments (`:106` and the `DELETE THIS THE DAY…` note at
`:346`) name `/v1/sensing/config` as the trigger to retire the bridge. **Anyone
probing that path will get a 404 forever, including after a perfect deploy.**
The go/no-go probe is `GET /v1/me/sensing` (browser session) or the device-agent
path above. Fix those two comments when the bridge is retired.

### 13.3 FOUR blockers, not two — verified against the live database

A granted gate needs all four. Only the first was previously recorded. Checked
tonight against `boltrig-postgres-1`:

| # | blocker | live evidence | refusal it produces |
|---|---|---|---|
| 1 | routes not deployed | openapi 230 paths, 0 sensing | `kernel_unreachable` |
| 2 | no device, so no credential | `select count(*) from devices` → **0**; `device_enrollments` → **0**; `~/.boltrig/` does not exist | `kernel_unreachable` |
| 3 | no camera binding | `select * from camera_bindings` → **0 rows**; `sensing_config` reads `camera_id` from that binding (`sensing_policy.py:261`) | `camera_not_bound` |
| 4 | camera defaults OFF | `select count(*) from user_settings` → **0**; `DEFAULT_CAMERA_ENABLED = False` (`sensing_policy.py:78`) | `camera_disabled` |

**Retiring the bridge tonight would have stood the camera down for four
independent reasons, not one.** Fixing only the deploy would still leave three.
Blockers 3 and 4 are the ones nobody had written down: even with a perfect image
and a perfect credential, the gate refuses until camerad publishes a binding
through `POST /v1/device-agent/{id}/camera-bindings` **and** the user turns the
camera on in Settings, which writes the `sensing.camera.enabled` row that does
not exist yet. The safe default is doing exactly what it was designed to do.

### 13.4 The credential could not be honestly forged

The task was to provision `~/.boltrig/sensing-agent.json` *the way the kernel
issues it*. That is a `device_session` scoped token: `authenticate_device`
(`device_route_support.py:38`) parses the scope, then matches
`token_digest(token)` against a `devices` row. Issuance is
`POST /v1/devices/enrollment/start` (human principal) →
`POST /v1/device-agent/enrollment/complete`. With **zero devices and zero
enrollments**, there is nothing to mint a token against, and hand-writing a JSON
file with an invented token would produce a credential the kernel rejects with
`invalid_device_session` — a file that looks provisioned and is not. **No
credential file was created.** `~/.boltrig/` still does not exist.

### 13.5 Two things sitting in the deploy path

Neither is a sensing defect; both will be hit by whoever does the deploy.

- **`boltrig-kernel-1` is already `unhealthy`** (FailingStreak 1420, up 12h).
  `/healthz` is 200, but `/readyz` reports `model_gateway: probe_failed`,
  required. Everything else is ok. **"The container went healthy" is therefore
  not a valid success signal for this deploy** — it is unhealthy now and will
  stay unhealthy. Use the openapi path count instead.
- **The live DB is at `0070_ai_config_modalities`; repo head is `0073`.**
  `/readyz` compares heads by strict equality, so an image built from this tree
  sits `not_ready` until alembic runs, and `roll-release.sh` does not run it.
  Migrate first, then deploy. No sensing migration is needed — all sensing state
  is `user_settings` rows, and `sensing_enrollments` is not a table and is not
  referenced by any code.

### 13.6 What WAS verified working tonight

- **The stop gesture is not regressed.** `character.prose_suggests_stop("his
  right hand is extended forward, palm open, near the camera")` → `True`;
  `""` → `False`; `"he is typing at the keyboard"` → `False`.
- **The camera is on and capturing.** `~/companion-frames/current.jpg` was 3
  seconds old at 23:14:37. camerad was **not** restarted — a second instance
  contends for the UVC device and recovery is a physical replug.
- **Gates green.** `apps/worker` tsc exit 0; vitest 806 passed / 87 files;
  `.venv/bin/python -m pytest tests/security tests/unit -q` → 2990 passed,
  142 skipped. No code was changed, so none of this is attributable either way.

### 13.7 Sequencing, so a restart does not blind the camera

Unchanged in spirit, longer than previously written:

1. Resolve or consciously accept `model_gateway: probe_failed`.
2. `alembic upgrade head` (0070 → 0073) **before** rolling the kernel image.
3. Rebuild and roll the kernel image. Rollback = re-tag the previous image and
   `up -d` the kernel alone — but the 0071–0073 migrations have **not** been
   checked for backward compatibility with the 0070-era image, so nobody should
   promise that rollback until they have been.
4. Confirm the route answers: `GET /v1/device-agent/{id}/sensing-config`, not
   `/v1/sensing/config`.
5. Enrol a device and write the mode-0600 credential from the enrollment
   response.
6. Let camerad publish a camera binding; turn the camera **on** in Settings.
7. Only when `camera_gate(force=True)` returns `granted` with
   `BOLTRIG_SENSING_UNMANAGED` unset: drop the env key from all three plists,
   delete the `UNMANAGED` constant and its branch from `capture_policy.py`, fix
   the two stale `/v1/sensing/config` comments, and restart the observer and
   presence. **Not camerad.**

Restarting before step 7 is safe but blank.
