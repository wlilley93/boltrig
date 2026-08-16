# Handover — unattended run, 2026-08-13

Written 18:00 BST while the operator was out. Everything below was verified on
the machine named; commands and outputs are quoted verbatim. Where a step was
not done, the reason is stated rather than the step being softened.

---

## 1. TOP ITEM WAITING: the `:8901` tailnet exposure is still open

**It was not closed in this run, and it should not be closed unattended.**

The Maya player runs on beelink and is mounted to the whole tailnet with no
credential. Verified from the M4 (a peer — never test a serve from its own host,
it returns 000 and looks broken):

```
$ curl -s -o /dev/null -w 'remote=%{http_code}\n' https://beelink.tailb4b671.ts.net:8901/remote
remote=200
$ curl -s https://beelink.tailb4b671.ts.net:8901/api/awareness
{"him": false, "present": false, "withheld": true, "reason": "no presence detector"}
```

No token, no auth. Every tailnet device — hanna-windows included — can load the
player and hit its API.

**Why it is not leaking today, and why that is luck rather than design.** Both
`/api/awareness` and `/api/memory` return `withheld: true` only because presence
is broken on beelink (§2). The broken gate is currently the only thing
protecting the diary, the fact sheet and the `/api/vigil` photographs. Fix
presence without closing this, and the same unauthenticated URL starts serving
them.

**Why it was left alone.** The fix is a proxy route added to beelink's intranet
server so the player is reached through the existing token-gated front door
instead of its own mount. That server is:

```
$ ssh -p 24222 jellytot@192.168.50.2 'ss -tlnp | grep :3000'
LISTEN 0 4096  100.113.51.76:3000  0.0.0.0:*
LISTEN 0 5      192.168.50.2:3000  0.0.0.0:*  users:(("python3",pid=2122297,fd=4))
$ pgrep -af intranet
2122297 /usr/bin/python3 /home/jellytot/intranet.py
```

That is a **live-service change on the shared build box**: editing
`/home/jellytot/intranet.py` and restarting it, then dropping the
`tailscale serve` mount for `:8901`. Both halves are one-way from the phone's
point of view — if the proxy route is wrong and the `:8901` mount is already
gone, the card on the phone simply stops working and there is nobody here to
notice or roll it back. beelink is also shared: a restart there is not private
to this task.

**The operator needs to be present to confirm the card still works after the
mount is dropped.** Do the two halves in one attended sitting: add the route,
load the card from the phone, confirm it works, *then* drop the `:8901` mount
and confirm again.

Until that happens, treat `https://beelink.tailb4b671.ts.net:8901` as an open
door held shut by a bug.

---

## 2. Presence is fine on the M4; the coupling to the player is broken and was NOT repaired

The briefing's premise — that `presence.jsonl` did not exist on the M4 — is
**wrong**. On the M4 it is healthy and recognising him:

```
$ pgrep -fl presence.py
82630 .../Python /Users/williamlilley/pixy-stream/presence.py
$ stat -f "%Sm %z" ~/pixy-stream/logs/presence.jsonl
2026-08-13 17:39:00  1726382          # wall clock at the time: 17:39:02
$ wc -l ~/pixy-stream/logs/presence.jsonl
11748
tail: {"type":"presence","dark":false,"known":true,"faces":1,"unknown":0,"best":0.7839,"ts":1786639140.79,"reused":true}
```

The whole chain works **on the M4**: `/usr/bin/python3 identity.py` →
`{"him": true, "age_s": 2.6, "reason": "recognised"}`.

The real fault is pure machine-locality. The player moved to beelink; the camera
did not and must not. On beelink:

```
$ ls -la ~/pixy-stream/logs/
ls: cannot access '/home/jellytot/pixy-stream/logs/': No such file or directory
$ tr '\0' '\n' < /proc/2236343/environ | grep -i PRESENCE
(nothing — PRESENCE_VERDICTS is unset)
```

So `identity.py:30` resolves to a path that does not exist, `_last_verdict()`
returns `None`, and `who()` returns `reason: "no presence detector"` — which is
exactly what `/api/awareness` returns above.

**Nothing was changed.** The diagnosis produced a complete, reviewed proposal
(one-line-only push of the last verdict from the M4 to beelink over the tailnet,
`0600`, `frame` and `best` stripped, plus `PRESENCE_VERDICTS` in the systemd
unit) but it was not applied for two reasons:

1. It is gated on `:8901` (§1). Repairing the gate while the endpoint is open is
   a net loss — it converts a withheld response into a served diary.
2. Step 1 of the proposal requires trusting beelink's host key under its
   **tailnet** name, which is currently absent:
   ```
   $ ssh-keygen -F "[192.168.50.2]:24222"
   # Host [192.168.50.2]:24222 found: line 14
   ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIE3s4xU4hUmp9JV8COciHenrj8djglohWpnagA5F2pHa
   $ ssh-keygen -F "[beelink.tailb4b671.ts.net]:24222"
   (nothing)
   ```
   Under launchd with `BatchMode=yes` there is no prompt, so a relay installed
   without that step fails silently forever.

The full proposal, with the script, the plist and the negative test that actually
proves the wiring (`reason` must become `"verdict stale"`, not
`"no presence detector"` — different code paths, `identity.py:59` vs `:56`), is
in the session record and should be applied in the same sitting as §1.

**Two data gaps the presence fix would not close.** On beelink
`~/Projects/gen-pipeline/store/personal/` contains only an empty `diary/` — no
`fact-sheet.md`. So even with presence repaired, `/api/awareness` returns
`him: true` with `entries: []` and `/api/memory` returns
`{"known": false, "reason": "no fact sheet yet"}`. The beelink port put the
player on the wrong side of *all* its personal data. **Do not rsync the personal
store to beelink to fix that** — it would put the diary, the fact sheet and 467
captured frames on a shared build box behind the endpoint in §1. That is what
Phase 3 (kernel) is for.

---

## 3. Push gate: the census now passes, the gate still fails on a missing `jq`

The claim-census blocker described in the briefing **is cleared**. Identical
numbers on the host and inside `boltrig-vm`:

```
$ .venv/bin/python scripts/check_claim_inventory.py
claims 1517 / SUBJECT-REACHED 318 / LOAD-BEARING, no subject 203 (baseline 203)
ORDINARY, no subject 838
RESULT: PASS - the inventory is current and the residue has not grown.
```

All 19 static gates pass on both, and `make typecheck` → `Success: no issues
found in 150 source files`.

**The gate still exits 2.** `make quality-gate` (the exact target the pre-push
hook calls) inside `boltrig-vm`:

```
3 failed, 3943 passed, 21 skipped, 3 warnings in 264.63s (0:04:24)
make: *** [Makefile:226: python-quality] Error 1
```

Coverage 86.65% against an 82% floor, so that is not it. All three failures are
in `tests/deploy/test_release_asset_reuse.py` with one root cause:

```
AssertionError: .../scripts/release_asset.sh: line 84: jq: command not found
assert 127 == 0
```

Confirmed environmental, not a code defect:

```
$ command -v jq                              # M4 host
/usr/bin/jq
$ orb -m boltrig-vm bash -lc 'command -v jq'
ABSENT-IN-VM                                  # re-verified 18:00
$ .venv/bin/python -m pytest tests/deploy/test_release_asset_reuse.py -q   # host
3 passed in 1.78s
```

The fix is one line of VM provisioning, **not a code change**:
`orb -m boltrig-vm bash -lc 'sudo apt-get install -y jq'`. It was not applied —
the task was read-only, and installing packages into the VM the gate runs in is
a change to the gate's own environment. GitHub's ubuntu runners ship `jq`, so CI
would not see this. Note the failing tests landed in `50b9373`, itself unpushed,
so this has never run green locally.

**Correction to the briefing on scope.** "commit 781346d is unpushed" understates
it by 21 commits:

```
$ git rev-parse --abbrev-ref HEAD; git rev-parse --short HEAD
feat/console-target
20eb6e8
ahead: 63  behind: 3
```

`781346d` is 21 commits back from HEAD. `feat/console-target` does not exist on
origin at all and has no upstream, so **all 63** are unpushed. Verified against
the live remote, not the 3-day-old cache: `git ls-remote --heads origin` returns
7 heads and `feat/console-target` is not among them; `origin/main` is still
`2be2396`, matching the cache, so the 63/3 counts are not distorted.

Also: the pre-push hook validates the **working tree**, not the committed tip
(`docs/HANDOVER-2026-08-10-familiar-console.md:163` says so). The tree is dirty
— 79 entries at 18:00, up from 42 earlier in the session. The census passes
*with that dirt included*, so the green above is a statement about the dirty
tree, not about `20eb6e8`.

There is **no `lane-lock.py` in this repo** (that is an opbox mechanism). The
hook is real and installed: `core.hooksPath` = `.githooks`,
`.githooks/pre-push` is `-rwxr-xr-x`. Pushing still needs the beelink relay —
the M4 has no GitHub credentials.

---

## 4. Observer repoint to the M1: landed, and now verified end to end

This is the one thing that is fully green.

`observe.py` was pointed off the retired `localhost:8100` VLM at the M1:

```
-VLM_URL = "http://localhost:8100/v1/chat/completions"
+VLM_URL = os.environ.get("VLM_URL", "http://mac-mini-m1:11434/v1/chat/completions")
+VLM_MODEL = os.environ.get("VLM_MODEL", "qwen3vl-abliterated")
```

At 17:40 this was proven reachable but **not** proven to write, because the
process was inside the operator's 30-minute stop-gesture pause (began 17:22:01,
`GESTURE_PAUSE_S = 1800`). That gesture was left alone rather than cleared.

**Re-checked at 18:00, after the pause expired at 17:52:01 — it writes.**

```
$ grep -nE '^- 1[6-9]:' ~/Projects/gen-pipeline/store/personal/diary/2026-08-13.md
141:- 17:52 A man with glasses and a beard sits shirtless at a desk...
...
150:- 17:59 A man with a beard and glasses sits shirtless at a desk, facing forward...
$ stat -f "%Sm" ~/Projects/gen-pipeline/store/personal/diary/2026-08-13.md
2026-08-13 18:00:14
```

Ten entries between 17:52 and 17:59, matching the observer log
(`logs/observe.log`, now 3583 lines). The 1395-line `Connection refused` stream
against the dead `:8100` ends permanently at the 17:21:43 restart and never
resumes. **Task #3 is closed.**

**The durability risk, which is not closed: the repoint is UNCOMMITTED.**
`git status` in `~/Projects/companion-observer` shows ` M observe.py` (also
` M pixy-ptz`, ` M pixy-ptz.m`, `?? pixy-ptz.bak`). The last commit touching
`observe.py` is `654e762` from 2026-08-12, which still contains the dead
`localhost:8100`. The running process (PID 80729) read the modified file at
startup so the fix is live in memory, but any `git checkout -- observe.py`,
stash, or clean-tree redeploy silently reverts the observer to the retired VLM
and reproduces the exact failure. **This is the single biggest durability risk
in the run.** Not committed, per instructions.

---

## 5. VJS submissions filed (3)

Filed rather than deferred back, per the standing rule. All three carry
`requested_order: TBD`, `court_requested: county`, `jurisdiction: default`,
`private_boundary: local`. Collision-checked against all 30 pre-existing
submissions and 24 orders — no `2026-08-13` id existed, and `grep -r` finds each
new id in exactly one file. **No orders were authored.**

| Case id | Asks |
|---|---|
| `SUBMISSION-2026-08-13-091412` | Does the tier-1 Chief of Staff identity resolve **in the Worker at dispatch, or in the kernel from the manifest**? The name and routing id ride the SDK contract to the Worker, but every dispatch-facing surface on both sides uses a hardcoded literal — `chat_turn_execution.py:66` stamps `owner_member="chief-of-staff"`, and `ChatRequest` has no target field at all, so the Worker could not address a tier-1 even if it resolved one. |
| `SUBMISSION-2026-08-13-104733` | Two real FrameGraph bakes (195.2 MB) sit in **another session's `/private/tmp` scratchpad** because `frame_bake.py:181` defaults `--out` to the CWD. Do they stay, move under `~/Projects/gen-pipeline/store/frames/`, or wait for the character-bundle root the spec calls for — and does that answer bind where future bakes are written? |
| `SUBMISSION-2026-08-13-152806` | Was "player on beelink only" meant to include **the 5.0 GB clip library**? Both machines already hold a byte-identical 875-file copy (`5,014,357,224` bytes each), neither is declared canonical, and the upscaler that reads it is destructive, Vulkan-bound and currently unrunnable on either box. |

Filed at `~/Projects/boltrig/.vjs/submissions/filed/`. All three parse under
`yaml.safe_load`.

**One further decision that should be filed and was not**: moving the presence
verdict off the sensor's machine makes the gate **spoofable** — anyone who can
write `/home/jellytot/.local/state/pixy/presence.jsonl` on beelink can put
`{"known":true,"ts":<now>}` there and open the fact sheet, the diary and the
vigil photographs. An HTTP pull has identical exposure, since whoever controls
beelink controls `PRESENCE_VERDICTS`. `0600` is a mitigation, not a fix. This is
inherent to running the policy on a different machine from the sensor. The
submission should read *"the presence gate now runs on a box that cannot verify
it"* and offer the two structural answers already in the plan (Phase 3 moves
presence and the gate into the kernel, or the player comes home to the M4). It
was not filed because it is downstream of the §1/§2 decision and would be
argued from a state that does not exist yet.

---

## 6. Doc corrections applied

Three files edited, all with the prior text superseded rather than deleted:

- `~/handover-2026-08-13-infra.md` — the M4 player is **booted out of the
  domain**, not merely stopped. `launchctl print gui/501/app.maya.player` →
  `Bad request. Could not find service "app.maya.player"`, plist parked as
  `~/Library/LaunchAgents/app.maya.player.plist.removed-20260813`. Nothing
  listens on 8901 or 8903 on the M4. Also corrected `app.pixy.presence  OFF` →
  `loaded, running` (pid 82630), and added the two live voice jobs
  `app.boltrig.pocket-voice` (:8911) and `app.boltrig.pocket-ears` (:8912),
  which were missing from the list entirely.
- `~/handover-2026-08-13-framegraph.md` — same player correction, plus an
  explicit warning that beelink's `:8901` mount is the unauthenticated exposure
  and not a supported route.
- `docs/VISION-2026-08-13-app-that-bakes-a-site.md` — gap 5 superseded:
  `~/Projects/pocket-voice` **is** the missing self-hosted route type. It serves
  `POST /v1/audio/speech` in OpenAI's shape, so boltrig carries one TTS adapter
  and varies the base URL. Verified live:
  `curl http://127.0.0.1:8911/healthz` → `{"ok":true,"loaded":true,...}`. The
  stale deployment-table row (`whisper-server :8910`, OmniVoice) was replaced —
  both are retired with plists parked `.disabled`, and `:8910` refuses
  connections.

**Two proposed corrections were rejected as false, and are worth knowing:**

- *"The Player is currently unreachable from the phone."* Not true — beelink
  still serves it to the whole tailnet, `/remote` → 200 (§1). The accurate
  conditional was written instead: the M4's player is gone; beelink's is
  reachable but *is* the exposure; once that mount drops, the Player is
  unreachable from a phone until the intranet proxy lands.
- The "self-hosted voice has no route type" claim was **not** in the three named
  handover docs — `HANDOVER-2026-08-13-voice-native-and-character-bundles.md` is
  already correct in three places. The stale claim was in the VISION doc, which
  was corrected instead.

**Unresolved and flagged rather than silently decided:** Pocket TTS throughput
is quoted three ways across the estate — `~11.6x` realtime
(`HANDOVER-2026-08-13-voice-native-and-character-bundles.md:51`), `9.83x`
(`pocket-voice/README.md`), and `7.72x` (`CLAUDE.md`). The README figure was
used and attributed to the README rather than picking a winner. **This needs a
re-measurement**; it was not benchmarked in this run.

---

## 7. Everything that was NOT done, and why

| Not done | Why |
|---|---|
| Close the `:8901` tailnet exposure | Live-service change on the shared box; the operator must confirm the phone card still works after the mount drops. **Top item.** |
| Install the presence relay | Gated on `:8901` — repairing the gate while the endpoint is open serves the diary to the tailnet. Also needs the tailnet host key trusted first, or it fails silently under launchd. |
| Commit the `observe.py` repoint | Instructed not to commit. Flagged as the biggest durability risk: a clean-tree redeploy reverts it to the dead `:8100`. |
| `apt-get install jq` in `boltrig-vm` | Read-only task, and it changes the environment the gate itself runs in. One line, no code change. |
| Push the 63 commits | Gate is red on the `jq` failure, and the M4 has no GitHub credentials (needs the beelink relay). |
| File the "gate runs on a box that cannot verify it" submission | Downstream of the §1/§2 decision; would be argued from a state that does not exist yet. |
| Clear the observer's stop gesture | Deliberately left alone — it was the operator's gesture. It expired on its own at 17:52:01 and the observer resumed correctly. |
| Benchmark Pocket TTS to settle 11.6x / 9.83x / 7.72x | Not measured; three conflicting figures left standing and attributed. |
| Rsync the personal store to beelink | Refused on purpose — it would put the diary, fact sheet and 467 frames on a shared box behind an unauthenticated endpoint. |

---

## 8. Plan doc correction the Phase 1 ordering rests on

The approved plan (`~/.claude/plans/swirling-zooming-sundae.md`) §1.3 says
presence is *"not loaded at all — it is absent from `launchctl list`"*. **That is
stale.** `launchctl list` on the M4 right now shows `app.pixy.presence`
(pid 82630) alongside `app.pixy.camerad` (62465), `app.companion.vigil` (83524)
and `app.companion.observer` (80729). Presence is loaded and running. The plan
was not edited — it is the approved plan — but Phase 1's ordering was written
against a fact that no longer holds.
