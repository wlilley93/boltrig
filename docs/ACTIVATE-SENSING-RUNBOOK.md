# Activating kernel-governed sensing — runbook

**Script:** `scripts/activate-sensing.sh`
**Written:** 2026-08-13, against the live kernel, the live database and this Mac's
AVFoundation camera list.
**Status when this was written:** nothing has been activated. Every step below is
un-run. The script's dry-run path and its own syntax are the only things verified.

---

## Read this first: the kernel is already unhealthy, and this does not fix it

`boltrig-kernel-1` reports **unhealthy** with a FailingStreak in the four figures.
That is **not** related to sensing:

```
/readyz        : not_ready
model_gateway  : {"status": "failed", "required": true, "reason": "probe_failed"}
migration      : {"status": "ok", "expected": "0070...", "current": "0070..."}
```

`model_gateway` is a **required** readiness check and it is already failing. The
container's healthcheck consults `/readyz`. Therefore:

> **The container will still say "unhealthy" after a completely successful
> rebuild.** "It came up healthy" is not available as a success signal here, and
> nothing in this runbook will turn it green.

Every postcondition in the script was chosen to discriminate *despite* that. If
you find yourself chasing `unhealthy` during this work, stop — you are chasing a
pre-existing fault that belongs to the model gateway, not to sensing.

---

## What is actually wrong

`capture_policy.camera_gate()` currently returns a GRANT **it never asked the
kernel for**, because `BOLTRIG_SENSING_UNMANAGED=1` is set on three launchd jobs.
That bridge exists because five independent things each refuse on their own.
Fixing one leaves the rest.

| # | Blocker | Evidence | Closed by |
|---|---|---|---|
| 1 | **The deployed image predates the code.** Not a wiring bug — `register_camera_agent_routes` already registers *both* `camera-bindings` and `sensing-config`. The live kernel serves the first and not the second. | `grep -c sensing` inside the container = **0**; source = **15**. `GET …/sensing-config` → **404**, `POST …/camera-bindings` → **401**. | step 2 (rebuild) |
| 2 | **`devices = 0`, `device_enrollments = 0`** — no credential can be minted. | live DB | step 3 |
| 3 | **`camera_bindings = 0`** → `sensing_policy` has no `camera_id` → `camera_not_bound`. | live DB | step 4 |
| 4 | **`user_settings = 0`** and `DEFAULT_CAMERA_ENABLED` is False → `camera_disabled`. | live DB | step 5 |
| 5 | **`BOLTRIG_DEVICE_LEASE_SIGNING_KEY` is not set** — not in `.env`, not in the container. `signer_for()` returns `None`, so **both** enrolment routes answer `503 device_leases_unavailable` before looking at anything else. | `.env`, container env | the `key` step |

Blocker 5 was not on the original list. Without it, fixing the deploy and the
database still leaves enrolment dead.

**The retirement path is `GET /v1/device-agent/{device_id}/sensing-config`.** The
string `/v1/sensing/config` that once appeared in a comment names a path that
does not exist and never did; anyone waiting on it waits forever.

---

## How to run it

**Dry run is the default. Without `--apply` the script changes nothing.** It runs
the real read-only precondition checks against the live system, prints the exact
commands and payloads it would use, prints the rollback, and stops.

```
./scripts/activate-sensing.sh <step>            # dry run — safe, always
./scripts/activate-sensing.sh <step> --apply    # does it, after a typed confirmation
```

Run **one step at a time and read the output.** Nothing runs anything else — no
step chains into the next. Under `--apply` each mutating step additionally
demands a typed confirmation phrase.

| Step | What it does | Mutates? |
|---|---|---|
| `0-preflight` | Reports where all five blockers stand | no, ever |
| `key` | Adds `BOLTRIG_DEVICE_LEASE_SIGNING_KEY` to `.env` | `.env` only |
| `1-migrate` | alembic 0070 → 0073 on the live DB | **live database** |
| `2-deploy` | Rebuilds the kernel image and recreates the container | **shared container** |
| `3-enrol` | Mints a device credential, writes it 0600 | DB + `~/.boltrig/` |
| `4-bind` | Publishes the camera binding | DB |
| `5-enable` | Turns the camera on in the owner's settings | DB — *this is the consent decision* |
| `6-verify` | Proves the gate GRANTS from the kernel | no |
| `7-retire` | **Prints** the retirement. Performs nothing. | no |

Plus `rollback-image`, `rollback-schema`, `rollback-sensing`.

---

## The order, and why it is that order

```
key  ──►  1-migrate  ──►  2-deploy  ──►  3-enrol  ──►  4-bind  ──►  5-enable  ──►  6-verify
```

- **`key` before `2-deploy`**, not after. `env_file` is read when the container is
  **created**. Adding the key to `.env` is inert until a recreate. Put it in
  first and the one recreate you are already doing picks it up; put it in
  afterwards and you need a second recreate.
- **`1-migrate` before `2-deploy`.** Readiness compares heads with **strict
  equality**. A new image on an old schema sits not_ready with a migration
  failure stacked on top of the model_gateway one, and you cannot tell them
  apart. Migrating first means the deploy has exactly one new variable.
- **`4-bind` before `5-enable`.** `PUT /v1/me/sensing/camera` re-checks the
  binding against `camera_bindings` (`_known_camera`) and answers **409
  `camera_binding_unavailable`** for a camera nobody published.

### Expected, transient weirdness between step 1 and step 2

After `1-migrate` and before `2-deploy`, the running *old* kernel asserts `0070`
while the database is at `0073`, so `/readyz` gains a migration mismatch. **This
is expected.** The kernel keeps serving; only `/readyz` changes. Close it by
running step 2 — do not chase it.

---

## What each check discriminates

Preconditions are read-only and run even in dry run. **A failed precondition
means nothing was done** — the script says so and exits without offering a
rollback.

**A failed postcondition means the step ran and did not take.** The script stops
dead, prints that step's rollback, and refuses to go further.

| Step | Postcondition | What it discriminates |
|---|---|---|
| `key` | the line is in `.env` | trivial, but it also *reminds you* the running container has not read it yet |
| `1-migrate` | `select version_num from alembic_version` == `0073_agent_model_routes` | the database's own report, not alembic's exit code |
| `2-deploy` (1) | `docker exec … grep -c sensing …camera_agent_routes.py` > 0 | **the file inside the running container.** Not the image, not the tag — the bytes actually being served |
| `2-deploy` (2) | `GET …/sensing-config` → **401**, not 404 | 404 = the old image is still serving; 401 = the route is live and refusing an unauthenticated caller. This is the single clearest signal in the whole run |
| `2-deploy` (3) | `/readyz` migration `expected == current` | catches a step-1 that silently did nothing |
| `3-enrol` | file mode is 600 **and** the minted token gets **200** from `sensing-config` | the shape check is not enough — a hand-written file passes that. This makes the kernel actually authenticate it |
| `4-bind` | the kernel echoes back the same `camera_id` we sent | catches a silently-coerced or partial write |
| `5-enable` | the **device-authenticated** `sensing-config` shows `enabled: true` with a `camera_id` | the settings write returning `ok` is not the point; what matters is what the *device* can read, because that is all `capture_policy` ever looks at |
| `6-verify` | `camera_gate(force=True)` returns GRANTED with `BOLTRIG_SENSING_UNMANAGED` emptied | the only honest proof: the gate granting **on the kernel's answer**, not on the bridge |

Notably absent from that table: **container health**. See the top of this
document.

---

## Rollbacks

| Step | Rollback |
|---|---|
| `key` | Delete the appended line from `.env`. A copy of the previous `.env` is saved in `~/.boltrig/sensing-activation/env.bak-<stamp>`. No container has read it, so nothing else is affected. Rotating this key later invalidates every enrolled device. |
| `1-migrate` | `./scripts/activate-sensing.sh rollback-schema --apply` (0073 → 0070). **0072's downgrade deliberately refuses** while any `device.file.list` lease exists. |
| `2-deploy` | `./scripts/activate-sensing.sh rollback-image --apply`. **The hinge:** `compose build` retags `boltrig/kernel:0.1.0`, and the running image has **no other tag** — it would become dangling and one prune would destroy the only way back. The script therefore tags the running image as `boltrig/kernel:rollback-<stamp>` *before* building. That retag **is** the rollback. |
| `2-deploy`, if step 1 also ran | The schema is at 0073 and the old image asserts 0070. It **will serve**, but `/readyz` gains a migration failure on top of the model_gateway one. Run `rollback-schema` too if you want the old readiness picture back. |
| `3-enrol` | `rollback-sensing` — revokes the device and moves the credential aside. A half-written credential is **worse than none**: it passes `capture_policy._credential()`'s shape check and is then rejected as `invalid_device_session`, so the host *looks* provisioned. |
| `4-bind` | **There is no delete route for `camera_bindings`.** The row stays, orphaned and inert — nothing reads a binding that no user setting points at. The withdrawal that counts is clearing the settings binding. |
| `5-enable` | `PUT /v1/me/sensing/camera {"enabled": false, "camera_id": null}`, i.e. `rollback-sensing`. |
| `6-verify` | Nothing — it is read-only. A refusal here means an *earlier* step did not really take. |
| `7-retire` | Re-add `BOLTRIG_SENSING_UNMANAGED=1` to the plists and reload. |

---

## What the script will not do, at all

- **It never touches camerad, presence or the observer.** A second `camerad`
  contends for the UVC device and recovery is a **physical replug**. Step 6
  proves the gate works with the bridge *still in place*, by emptying
  `BOLTRIG_SENSING_UNMANAGED` for one short-lived probe process. No plist is
  edited, no daemon restarted.
- **It never edits `capture_policy.py`.**
- **It never restarts postgres, redis, hatchet or the fleet worker.** `--no-deps`
  is on the one `compose up` in the file and is load-bearing: hatchet-lite
  regenerates its keyset on recreate, which would invalidate the worker's token.
- **It never commits, checks out or cleans anything in git.**
- It takes **no database dump**. Step 1 prints the `pg_dump` command and tells
  you to run it yourself if you want one — writing a backup nobody verified is
  worse than saying plainly that there is none.

---

## Things to watch

**Step 2 bakes the working tree, not a tag.** Preflight prints
`git status --porcelain -- boltrig/` for exactly this reason. If uncommitted
files appear there that are not the sensing work, another session's
work-in-progress is about to be deployed. Stop and ask them. (At the time of
writing `boltrig/` is clean at `6b516e0`.)

**Step 2 takes the kernel away from other sessions** for about one boot.

**The `camera_id` is derived, not configured — and it is derived from where the
camera is PLUGGED IN.** An earlier draft of this paragraph said the fingerprint
was `sha256_hex(AVCaptureDevice.uniqueID)` in `camera_discovery.rs`. That was
wrong on both counts, and the prose-reference gate caught it. The real
derivation is in `apps/worker/src-tauri/src/camera_uvc.m`: it builds a
`native_key` from the **libusb bus and port path** (`"%u.%u..."` down the port
chain, or `address-<n>` when the topology is unavailable), takes `CC_SHA256` of
that string, and `camera_id = "camera_" + fingerprint[:32]`.
`camera_discovery.rs` only *carries* the value.

That distinction has an operational consequence, which is why it is worth the
paragraph: **moving the camera to a different USB port changes its identity.**
The binding will not match, `camera_gate` will return `camera_not_bound`, and
nothing about the camera itself will have changed. Re-bind rather than debug.

The script re-derives the value live from `system_profiler` (enumeration only —
it does **not** open the device, so it does not contend with the ffmpeg camerad
is holding) rather than hard-coding it. On this machine, in its current port,
that is `camera_346036ec09ab7f8459c89b69e2d34e82` for the EMEET PIXY. If the
value the script prints differs, find out why before binding.

**PTZ states are declared `unknown` on purpose.** `"proven"` additionally
requires the evidence string
`bounded_uvc_set_readback_frame_change_and_exact_restoration`, and this path
probed no UVC. Nothing downstream reads those fields anyway — `sensing_config`
carries only `camera_id` and `descriptor_fingerprint`.

**A PAT will not do.** `BOLTRIG_AUTH_MODE=session`. A PAT satisfies
`enrollment/start` (`actor_tier == "human"`) but is refused **403** by
`PUT /v1/me/sensing/camera`, which demands `is_interactive_credential()` —
`INTERACTIVE_CREDENTIAL_KINDS` is `{session, federated, dev-header}`. The script
logs in with a cookie, once per step that needs it. Set `BOLTRIG_LOGIN_PASSWORD`
to avoid the prompt, or type it.

**Presence stays off.** `PUT /v1/me/sensing/presence` answers 409 until an
enrolment with a room-calibrated threshold is published over
`POST /v1/device-agent/{id}/sensing-enrollment`. Separate job.

---

## The 24-hour problem — CLOSED 2026-08-14, with one bound you must know

`device_route_support.SESSION_TTL` is **24 hours**, enforced in SQL by
`authenticate_device_session`'s `session_expires_at >= now()`. `capture_policy`
used to have no rotation code at all, so roughly a day after step 3 every
`sensing-config` poll returned 401, the gate read `kernel_unreachable`, and the
camera stood down — correct fail-safe behaviour and a daily outage.

**`capture_policy._maybe_rotate()` now renews the session**, called from the top
of `camera_gate()` on every poll. It is a pure function of `(now, expires_at)`
with no timer behind it, so a daemon restarted every ten seconds behaves like one
up for a week.

**RENEWAL IS PREVENTION, NOT REPAIR — and this is the bound.** `rotate_session`
calls `authenticate_device` *first*, which requires a live session, so there is
no route from a lapsed token back to a live one. The only re-issuance path is
`POST /v1/devices/enrollment/start`, which demands `actor_tier == "human"`. The
design therefore renews at the **halfway mark** (`ROTATE_MARGIN_S = 12h`), which
buys two rotations a day and a **12-hour kernel-outage budget**: the kernel may be
unreachable that long and the session still renews when it returns. Past that the
session lapses and **only a human re-enrolment brings it back**. That is the
honest cost, and it is stated rather than hidden.

**Revocation is still absolute, and for the same reason.** `revoke_device` sets
`revoked_at` *and* NULLs both session columns, so every later rotate is a 401
forever, and these daemons hold no human credential to re-enrol with. A retry loop
cannot defeat the control because there is nothing for it to converge on.

**Three daemons share one credential**, and the kernel keeps exactly one live
token per device. A non-blocking `flock` on `~/.boltrig/sensing-agent.lock` means
one daemon rotates per window; the new token is written back to the shared file
atomically and `_credential()` re-reads it every poll, so the other two adopt it
on their next tick, un-restarted.

### What was measured, 2026-08-14

| Proof | Command | Result |
| --- | --- | --- |
| Unit suite | `python -m unittest discover -s tests` in `~/Projects/companion-observer` | **23/23** on 3.14, 3.11 and 3.9 |
| Real kernel, real enrolment, expiry survived + revocation | in-process `create_app` + `InMemoryStore`, driven through `capture_policy` | **27/27**; ran t+0h→t+73h with **zero** stand-downs across the original 24h expiry, 6 real rotations |
| Three real processes, one credential, shipping constants | three OS processes against a real kernel on loopback | **1** rotation host-wide, 2 transient refusals out of 180 polls, all three ended `granted` |
| Same, contention forced ~4000× real rate | as above with margin opened and floor removed | 120 polls, all three recovered, **no permanent lockout** |

A concurrent rotation can still cost a sibling **one** poll: its in-flight request
was authenticated with a token that got retired mid-flight. `_fetch` re-reads the
credential and retries **once**; if it loses twice it refuses that tick and
recovers on the next. The camera skips one frame. It does not stand down.

---

## Step 7 — the retirement, which you do yourself

Step 7 prints and performs nothing, in `--apply` or out of it. Do it only once
you have watched step 6 pass.

**(a) Three plists** carry `BOLTRIG_SENSING_UNMANAGED` — note that this is three,
not two:

```
~/Library/LaunchAgents/app.companion.observer.plist
~/Library/LaunchAgents/app.pixy.presence.plist
~/Library/LaunchAgents/app.pixy.camerad.plist
```

Remove the `<key>` and its `<string>1</string>` from each, then reload that job:

```
launchctl bootout   gui/$(id -u)/<label>
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/<label>.plist
```

**Order matters and camerad is last.** Reloading camerad restarts it, and a
second camerad contending for the UVC device is recovered only by physically
unplugging the Pixy. Observer first (its restart costs nothing), then presence,
then camerad alone and watched.

**Renewal does not need camerad's restart, and that is deliberate.**
`_credential_blob()` ignores unknown keys, so a camerad still running the
pre-rotation module keeps working from a file a restarted observer has already
added `expires_at` to. **Rotation goes live as soon as one of the three
restarts.** Restart observer, watch a renewal happen (below), and only then take
camerad's single, watched restart — the one this step already required.

**(b) One branch in `capture_policy.py`**, in
`~/Projects/companion-observer/capture_policy.py`:

- **line 111** — `UNMANAGED = os.environ.get("BOLTRIG_SENSING_UNMANAGED", "") == "1"`,
  with its comment on lines 106–110
- **lines 821–857** — the whole `if UNMANAGED:` branch inside `camera_gate()`,
  ending at
  `return Decision(True, GRANTED, "unmanaged host: no kernel sensing route", {})`

Delete both. `camera_gate()` then runs `_maybe_rotate()` and goes straight to
`config, reason, detail = sensing_config(force)` — the code step 6 just proved
GRANTS. **Leave the `_maybe_rotate()` call where it is, above the branch.** It is
above it on purpose: the UNMANAGED branch returns without ever polling, so a
renewal hung off the poll would never run on a bridged host and the credential
would lapse inside the very window step 7 has to be reachable in.

### New gate before you do any of this: watch one real renewal

Do not accept "the code is there". The runbook's own standard is to have seen it.

1. Restart **observer only** (its restart costs nothing).
2. Note the token and `expires_at` in `~/.boltrig/sensing-agent.json`.
3. Force the margin in a *probe process* — never by editing the module's
   constant:
   ```
   cd ~/Projects/companion-observer && ./.venv/bin/python -c "
   import capture_policy as p
   p.UNMANAGED = False; p.ROTATE_MARGIN_S = 10**9; p.ROTATE_ATTEMPT_FLOOR_S = 0
   print('rotated:', p._maybe_rotate())"
   ```
4. Confirm the token **changed** and `expires_at` **advanced ~24h**, and that the
   old token now 401s while the new one 200s on
   `GET /v1/device-agent/{id}/sensing-config`.

Only then remove the bridge.

> **The 24-hour problem is closed** (see the section above, and the measurements
> in it). What remains before retiring the bridge is the *other* three blockers
> the `capture_policy.py` comment names — the deployed kernel image predating the
> `sensing-config` route, no enrolled device, and no camera binding — plus the
> step above. Those are steps 1–6 of this runbook, and they are the operator's.
