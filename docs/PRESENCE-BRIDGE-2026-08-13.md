# The presence bridge — beelink pulls the M4's verdict over the cable

**Status: SHIPPED and proven, 2026-08-13. INTERIM — see "What replaces this".**
Companion to `CLOSURE-8901-2026-08-13.md`, which had to land first.

## The problem

The camera and the enrolment live on the M4. `app.pixy.presence` watches
camerad's feed and appends a verdict to `~/pixy-stream/logs/presence.jsonl`
every ~8s. The Maya player was ported to beelink, and beelink has no camera, so
`identity.py` fell back to a path that does not exist there:

```python
VERDICTS = os.environ.get("PRESENCE_VERDICTS") or os.path.expanduser(
    "~/pixy-stream/logs/presence.jsonl")
```

`_last_verdict()` returned `None`, and every gated endpoint answered
`{"withheld": true, "reason": "no presence detector"}` — the fail-closed path,
firing permanently. Maya could not recognise him on the box she now runs on.

## Why this could not ship an hour earlier

Until this afternoon the player was published to the whole tailnet
unauthenticated on `:8901`. Repairing presence then would have converted a
UI-shell leak into a **served diary** — the observer's durable fact sheet about
a real person, readable by any tailnet device. `CLOSURE-8901` removed the
`:8901` serve mount, pinned the player to `127.0.0.1`, and put `/remote` behind
the intranet's Tailscale-identity gate on `:3000`. Repairing presence now puts
the diary *behind* that gate.

## The transport, and why it is a PULL over SSH

```
   M4 (192.168.50.1)                          beelink (192.168.50.2)
   ────────────────────                       ──────────────────────
   app.pixy.presence                          presence-pull.timer  (15s)
      └─ presence.jsonl  ──┐                        │
                           │                        │ ssh -i id_presence_bridge
   sshd :22 ◄──────────────┴────── direct cable ────┘   (Apple-signed sshd)
      └─ forced command:                              │
         /usr/bin/python3 presence-verdict.py         ▼
         → {"ts","dark","known","faces"}        ~/.cache/maya/presence.jsonl
                                                      │  (mode 600, 69 bytes)
                                                      ▼
                                          maya-player.service
                                          Environment=PRESENCE_VERDICTS=…
                                                      │
                                          identity.who() → /api/awareness
```

**The M4 makes no outbound connection at all.** That is the whole point.

### The trap this avoids

macOS Local Network permission is **per-BINARY**, and it gates *outbound*
connections to `192.168.x` from non-Apple-signed binaries. A launchd job on the
M4 pushing over the cable is exactly the shape that has cost hours before, and
its failure is silent: presence goes stale, `who()` fails closed, and Maya just
quietly stops recognising him with no error anywhere.

The previous agent measured the alternatives rather than assuming:

| option | measured result |
| --- | --- |
| **(a) beelink pulls HTTP from an M4 cable listener** | **Fails today.** The listener bound `192.168.50.1:8977` and the cable was healthy (0.606ms, 0% loss), but beelink got `rc=28` and *the M4 could not reach its own listener*. `socketfilterfw --getglobalstate` = enabled, "automatically allow **signed** software"; the venv python is `Signature=adhoc`. Fixing it needs a per-binary firewall exception that a venv rebuild silently invalidates. |
| **(b) M4 pushes from launchd** | Works right now — and that is why it is disqualified. The trap did not reproduce, but nothing in the config explains why, so it is undocumented mutable state an OS update or a Local Network reset can re-arm. It also points the trust arrow the wrong way: an M4-held credential *into* the shared build box. |
| **(d) reuse camerad** | Rejected on payload, not transport. camerad serves `/snapshot.jpg`; using it means moving JPEGs off the M4 *and* rebinding it off loopback. |
| **(c) beelink pulls over SSH** | **Chosen.** No M4 outbound connection, so no TCC or firewall state can break it. SSH is the one path with a durable Apple-signed allowance already in the firewall list — `/usr/libexec/sshd-session` and `/usr/bin/ssh` both show *(Allow incoming connections)*. |

## The record that crosses the cable

`~/pixy-stream/presence-verdict.py` on the M4, run by the forced command:

```json
{"ts": 1786653846.271869, "dark": false, "known": false, "faces": 0}
```

69 bytes. One record — the **last** verdict, not the 13,525-line history.
`identity.who()` (lines 54–65) reads only these four fields.

Deliberately dropped, and confirmed absent on beelink:

| dropped | why |
| --- | --- |
| **`frame`** | a filesystem path to a **JPEG of an unrecognised person**. `presence.py:228` writes these to `logs/unknown/` — there are 828 of them. None crosses the cable. |
| `best` | the face-match score. |
| `unknown` | permanently ≥1 because insightface sees the child's photo on the wall calendar; means nothing. |
| `reused`, `type`, `detail` | detector internals. |

`presence-verdict.py` also folds `type == "camera_error"` into `dark`, so a
dead lens reads as "I cannot see" rather than "nobody there".

The puller re-filters on arrival (`ALLOWED = {"ts","dark","known","faces"}`) so
beelink cannot come to hold a `best` or a `frame` even if the M4 side regresses.

> **One open question for the operator.** The authorisation said *"the
> four-field verdict"*, and the four fields are `ts/dark/known/faces` — that is
> what ships. A later instruction said to strip `faces` as well, which would
> make it three. `faces` is a bare integer count with no identity in it, and it
> changes only the *reason string* (`"no match"` vs `"nobody there"`), never
> `him`. To drop it: delete `"faces"` from `ALLOWED` in `presence-pull.py` and
> from the `print(json.dumps(...))` in `presence-verdict.py`. Nothing else moves.

## The key restriction is load-bearing

A **new** dedicated keypair, generated on beelink so the private half never
crossed a wire: `~/.ssh/id_presence_bridge` (ed25519, no passphrase, mode 600).
Its line in the M4's `~/.ssh/authorized_keys`:

```
from="192.168.50.2",command="/usr/bin/python3 /Users/williamlilley/pixy-stream/presence-verdict.py",restrict ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAILJW2Wy3A8PxkmD60EOH++heeBdbCMS24maxYkabLvLc presence-bridge
```

beelink runs foreign docker builds, so the worst a stolen copy of this key may
yield is those four fields — never a read of arbitrary M4 files.

`from=` is doing real work, not decoration: `sshd -T` shows
`listenaddress 0.0.0.0:22`, so the M4's sshd **is** on the tailnet. The
discriminator it matches is the source address, which differs by path:

```
beelink -> 192.168.50.1   SSH_CONNECTION=192.168.50.2  49704 192.168.50.1  22
beelink -> 100.121.178.18 SSH_CONNECTION=100.113.51.76 49470 100.121.178.18 22
```

The interpreter is **`/usr/bin/python3`**, not the venv: stdlib-only,
Apple-signed, and so the forced command survives a venv rebuild.

## Proofs

Every claim below was run, not reasoned.

### 1. The key does only one thing, from only one place

```
T1  cable, no command
    $ ssh -i id_presence_bridge williamlilley@192.168.50.1
    {"ts": 1786652914.107826, "dark": false, "known": false, "faces": 0}   rc=0

T2  tailnet — MUST fail
    $ ssh -i id_presence_bridge williamlilley@100.121.178.18
    Permission denied (publickey,password,keyboard-interactive).           rc=255

T3  command override — ask for a private key, get the verdict
    $ ssh -i id_presence_bridge williamlilley@192.168.50.1 'cat ~/.ssh/id_ed25519'
    {"ts": 1786652914.107826, "dark": false, "known": false, "faces": 0}   rc=0
    (same with 'env' as the requested command)

T4a remote forward — MUST fail
    $ ssh -i … -o ExitOnForwardFailure=yes -N -R 19998:127.0.0.1:22 …
    Error: remote port forwarding failed for listen port 19998             rc=255

T4b local forward — binds locally, but carries nothing
    $ ssh -i … -N -L 19999:127.0.0.1:8911 …   then curl 127.0.0.1:19999
    curl: http_code=000 exit=56
    ssh: channel 2: open failed: administratively prohibited: open failed
```

T4b matters: the *first* attempt at it accidentally used beelink's default key
(zsh does not word-split unquoted parameters, so `ssh $O` passed the whole
option string to `-i`) and the tunnel **worked**, returning a 404 from the M4's
loopback-only pocket-voice on `:8911`. See "Pre-existing exposure" below.

### 2. The endpoints are repaired

Before, all three: `{"withheld": true, "reason": "no presence detector"}`.
After, from the M4 through the authenticated intranet:

```
$ curl https://beelink.tailb4b671.ts.net:3000/api/awareness
{"him": false, "present": false, "withheld": true, "reason": "nobody there"}
$ curl … /api/memory
{"known": false, "withheld": true, "reason": "nobody there"}
$ curl … /api/vigil
{"withheld": true, "reason": "nobody there"}
```

`"nobody there"` is the **success** string. It comes from `who()`'s last line,
which is only reachable once a verdict was read and found fresh; "no presence
detector" is the branch taken when there is no verdict at all. Detector
present, nobody in frame.

The other branches, exercised against a temporary file on beelink (a unit test
of the plumbing, not a claim about the room — the file was removed):

```
known=true, ts=now      -> {"him": true,  "age_s": 0.0,   "reason": "recognised"}
known=true, ts=now-300  -> {"him": false, "age_s": 300.0, "reason": "verdict stale"}
real bridged file       -> {"him": false, "age_s": 5.8,   "reason": "nobody there"}
```

The detector does produce `known=true` — 6,773 of 13,525 records in the current
log, most recently 695s before this was written. `him:true` end-to-end was **not**
observed, because nobody was in frame during the work; the four fields that carry
it are the same four proven flowing above.

### 3. Freshness

```
$ date -u                              20:42:56
$ stat -c %y ~/.cache/maya/presence.jsonl
                                       2026-08-13 20:42:54   -> age 2s
$ journalctl --user -u presence-pull.service
  20:41:34 … 20:41:50 … 20:42:06 … 20:42:21 … 20:42:37 … 20:42:53   (15s apart, all Finished)
```

Cadence: presence.py writes every ~8s, timer pulls every 15s, `MAX_AGE_S` is 60.
Worst case ≈ 23s. One dropped pull still lands ≈40s, so a blip does not flip him
to "not him"; two consecutive failures do, which is correct.

### 4. Not tailnet-readable

```
$ curl http://100.113.51.76:8901/api/awareness            exit=7 (refused)
$ curl http://beelink.tailb4b671.ts.net:8901/api/…        exit=7 (refused)
$ curl http://192.168.50.2:3000/api/awareness             403 not authorized
$ ssh -i id_presence_bridge williamlilley@100.121.178.18  Permission denied

$ ss -ltnp | grep 8901
LISTEN 0 5   127.0.0.1:8901  0.0.0.0:*  users:(("python",pid=2742199,fd=3))
```

The player holds **loopback only** — not `0.0.0.0`, not `100.113.51.76`. The
`100.113.51.76:3000` listener is tailscaled's own serve proxy, which injects
`Tailscale-User-Login`; the intranet's `authed()` requires that header *and*
`handler.on_socket` (arrived on the ts-input socket), which is why the same
request over the cable returns 403. The verdict file itself is `-rw------- 1
jellytot` and is served by nothing.

*Honest limit:* the 200 responses were fetched from the M4, an authorised
tailnet identity. A refusal from an **unauthorised** identity was not tested —
only authorised ones are available here. The cable 403 proves the same
`authed()` gate is live and denies on missing identity.

### 5. Stripping

```
M4 raw:      {"type":"presence","dark":false,"known":false,"faces":0,
              "unknown":0,"best":null,"ts":1786653789.41,"reused":true}
M4 raw with a frame:
             {…,"best":0.112,"frame":"/Users/williamlilley/pixy-stream/logs/unknown/1786601043009.jpg",…}
keys ever in that log:
             ['best','detail','faces','frame','known','reused','ts','type','unknown']

beelink got: {"known": false, "ts": 1786653846.271869, "dark": false, "faces": 0}
             lines: 1        keys: ['dark','faces','known','ts']        69 bytes
             best/frame/unknown/reused/type/detail/embedding: all absent
             find ~/.cache/maya ~/Projects/maya-remote -newermt … \( -name '*.jpg'
               -o -name '*.png' -o -name '*.npz' \)   ->  nothing
             ~/pixy-stream does not exist on beelink
```

### 6. Stripped environment

The forced command runs under sshd, and the puller under systemd — neither gets
an interactive shell's environment.

```
M4:  $ env -i /usr/bin/python3 ~/pixy-stream/presence-verdict.py
     {"ts": 1786653748.84, "dark": false, "known": false, "faces": 0}   rc=0
     $ env -i HOME=/nonexistent /usr/bin/python3 …
     rc=1, no output   (fails CLOSED — consumer keeps the old file and ages out)
     $ ssh -i id_presence_bridge … 'env'
     {"ts": …}          (the forced command ignores it entirely)

beelink: $ env -i HOME=/home/jellytot PATH=/usr/bin:/bin \
             /usr/bin/python3 ~/bin/presence-pull.py
     rc=0, file written, mode 600
     (no SSH_AUTH_SOCK, no agent — the key is used directly via -i +
      IdentitiesOnly=yes, so agent-less systemd is the tested case)
```

`StrictHostKeyChecking=yes`, with `192.168.50.1` already in beelink's
`known_hosts`: a spoofed M4 cannot feed fabricated verdicts.

### 7. Survives reboot, both ends

```
M4:      Remote Login: On                              (sshd is a system launchd job)
         app.pixy.presence.plist  RunAtLoad=true  KeepAlive=true
         nothing new was added to the M4 — the bridge adds no M4 daemon
beelink: loginctl show-user jellytot -p Linger  ->  Linger=yes
         ~/.config/systemd/user/timers.target.wants/presence-pull.timer -> …
         systemctl --user is-enabled presence-pull.timer maya-player.service -> enabled, enabled
         presence-pull.timer has OnBootSec=30s
```

## What changed

| file | change |
| --- | --- |
| M4 `~/.ssh/authorized_keys` | +1 line (`from=`/`command=`/`restrict`). Backup: `authorized_keys.bak-pre-presence-bridge-20260813` |
| M4 `~/pixy-stream/presence-verdict.py` | pre-existing, unmodified |
| beelink `~/.ssh/id_presence_bridge{,.pub}` | new keypair |
| beelink `~/bin/presence-pull.py` | new |
| beelink `~/.config/systemd/user/presence-pull.{service,timer}` | new, timer enabled |
| beelink `~/.config/systemd/user/maya-player.service` | +1 `Environment=` line and its comment. Backup: `maya-player.service.bak-pre-presence-bridge-20260813` (alongside the earlier `.bak-pre-loopback-20260813`) |
| beelink `~/.cache/maya/presence.jsonl` | new, mode 600, rewritten atomically every 15s |

`--host 127.0.0.1` on the player is untouched. pocket-voice, camerad and the
player all still bind loopback. beelink-prod, Salad, R2 and every tailscale
serve mount were not touched.

## Rollback

```bash
# beelink
systemctl --user disable --now presence-pull.timer
rm -f ~/.config/systemd/user/presence-pull.{service,timer} ~/bin/presence-pull.py
rm -f ~/.cache/maya/presence.jsonl ~/.ssh/id_presence_bridge{,.pub}
cp ~/.config/systemd/user/maya-player.service.bak-pre-presence-bridge-20260813 \
   ~/.config/systemd/user/maya-player.service
systemctl --user daemon-reload && systemctl --user restart maya-player.service

# M4 — revoking the key alone is enough to sever the bridge
cp ~/.ssh/authorized_keys.bak-pre-presence-bridge-20260813 ~/.ssh/authorized_keys
```

Rolling back returns the three endpoints to
`{"withheld": true, "reason": "no presence detector"}`. Nothing else regresses.

## Pre-existing exposure this work uncovered — NOT introduced here

The stated threat model is that a stolen beelink key should yield only four
fields. **It would not today.** beelink's general-purpose
`~/.ssh/id_ed25519` (`SHA256:2tP1tPfTprCO2LnvwWg3RXlHLPdklr6UWJc4YuvWvBE`) is in
the M4's `authorized_keys` **unrestricted**, and authenticates to a full shell
**from the tailnet**. The accidental T4b run above used it to tunnel into the
M4's loopback-only pocket-voice on `:8911` and got a live HTTP response.

The restricted key is still right — it bounds *this* bridge. But it does not
bound the blast radius while that unrestricted line stands, on a box that runs
foreign docker builds. That is larger than anything this bridge adds and wants a
separate decision.

## What replaces this — INTERIM

This is a file on a box that happens to also run the consumer. Phase 3 of the
plan makes presence a **Boltrig service writing to the kernel**: `observe.py`
splits at the seam, camerad and presence move into Boltrig, and consumers ask
the kernel "is he here" rather than tailing a JSONL that a timer happens to
keep fresh. At that point `PRESENCE_VERDICTS`, `presence-pull.timer`, the
restricted key and this document all retire together. Until then the bridge is
the seam, and it is deliberately narrow enough to delete in one commit.
