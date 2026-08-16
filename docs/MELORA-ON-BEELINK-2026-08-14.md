# me-lora on beelink — migration and M4 retirement

**Date:** 2026-08-14
**Decision:** beelink is the only me-lora. The M4 copy is retired.
**Status:** containers removed from the M4. **Volumes kept.** Voice bridge landed but
**not wired into the container** — see [Known gap](#known-gap-the-voice-bridge-stops-at-the-host).

---

## 1. Where me-lora lives now

| | before | after |
| --- | --- | --- |
| UI | M4 `me-lora-ui`, published **0.0.0.0:8000** | beelink `me-lora-ui`, published **127.0.0.1:8000** |
| MinIO | M4 `me-lora-minio` 127.0.0.1:9000-9001 | beelink `me-lora-minio` 127.0.0.1:9000-9001 |
| Model endpoint | `OLLAMA_URL=http://mac-mini-m1:11434` | `OLLAMA_URL=http://100.108.41.109:11434` (same box, M1, by tailnet IP) |
| Voice refs | bind `~/Projects/pocket-voice/refs` | `/home/jellytot/me-lora-mounts/voice-refs` (**not yet mounted into the container**) |

beelink reaches the tailnet at `https://beelink.tailb4b671.ts.net:8000` via `tailscale
serve` (tailnet-only, not Funnel). The app itself is the only thing standing in front of
it — form login at `POST /login`, username `williamlilley`. A wrong password returns 401
and every `/api/*` route returns 401 without a session cookie. Both verified.

The M4's publish was `0.0.0.0:8000`; beelink's is `127.0.0.1:8000`. The move **tightened**
the network posture.

---

## 2. What moved

### Volumes (all four)

Content was compared by **sha256 of every file on both boxes**, not by size. Regenerated
fresh on 2026-08-14, after the migration, immediately before deleting anything.

| volume | M4 files | beelink files | content unique to M4 |
| --- | --- | --- | --- |
| `me-lora_ui-dataset` | 105 | 105 | **0** — manifests byte-identical |
| `me-lora_ui-outputs` | 230 | 332 | **0** |
| `me-lora_ui-configs` | 28 | 33 | **0** |
| `me-lora_minio-data` | 162 | 3204 | 0 real objects (38 `.minio.sys` internals only) |

MinIO holds 3 LoRA objects plus `robots.txt`. Each is a 38-part multipart upload and
**all 41 part hashes are present on beelink**:

```
me-lora/lora/0ac023776ae84497b0674206626dcce6.safetensors   38 parts, 38 matched
me-lora/lora/bce0c629f1fd4b899f65247941ebbb91.safetensors   38 parts, 38 matched
me-lora/lora/e874c34c7c124eddb91d14243eac00ec.safetensors   38 parts, 38 matched
me-lora/robots.txt                                           1 part,   1 matched
```

The 879M-vs-6.0G size gap between the two MinIO volumes is `.minio.sys` bookkeeping
(trash, usage caches, bloom cycles). It is not data.

### The 9 files that existed only on the M4

These are the reason this was a migration and not a deletion. All nine now live on
beelink at their original paths, verified by sha256 on both sides:

```
c392e622b5384bb170dd37d46303f5d36b37830dc242807c729aaaef294eea16  .voice-register-choices.json
28e05874226850a834be3995fe5eb80d8ce95a3d0b8d0935b45903f31ed53934  voice-20260813-172605-maya.wav
9b67403626a58e3b7f501e1676e3cd8e02b7ccee7f521cba9cc2f427758a53dc  voice-20260813-173151-alba.wav
a1c0eb967b898883c245c60544af254c00732e10559d78889ff1a7ee4455968f  voice-20260813-173151-maya.wav
020f041a45066a76f00f30af44ba0531efcd8d972436ef56fcc7ff063500ca6e  voice-20260813-173344-maya.wav
24993bb7fd467ff42f89d3f8537b179d174218fda29fad15fd851d9aa775c34b  voice-20260813-173603-maya.wav
a7c54b732fc21b1c5e91ccac434a579823863aeb08c03b2ff1d9185773a920f8  voice-20260813-174436-maya.wav
7d40669854366caa22e55df3c77eabe6d7a6c4285c740fe25d4f351ec98eae13  voice-20260813-191625-maya.wav
92d22392e54af26306dae8c449543c0c6581f0f69570896696b17cec665c2f46  voice-20260813-191943-maya.wav
```

`.voice-register-choices.json` is the only record of the register audition. Its hash was
re-read **from inside beelink's running container** after the M4 containers were removed
and still reads `c392e622…eea16`.

Note the count: **8 wavs, not 7.** `voice-20260813-173151-alba.wav` is a different
character and was nearly missed.

### Covers — a same-path collision, both sides preserved

Three cover PNGs existed at the same paths on both boxes with **different content**.
Copying "preserving paths" would have destroyed beelink's live cover art. Both variants
are kept and beelink's live files were left in place:

```
covers/_m4-variants-20260813/Luna.png                   f11b60ce…c83d73
covers/_m4-variants-20260813/folder_Luna_Faceswap.png   27ada4bc…2660f1a
covers/_m4-variants-20260813/folder_Luna_Lora.png       d933644d…e5540b
covers/_beelink-backup-20260814/Luna.png                5d4d87b6…6c03b5
covers/_beelink-backup-20260814/folder_Luna_Faceswap.png b6e3b8e4…b01170
covers/_beelink-backup-20260814/folder_Luna_Lora.png    e3c9134f…15ac7e
```

beelink's live copies win because its library is the fuller one (317 files vs 230) and it
has `Luna/Faceswap/` live where the M4 has it only under `_deleted/` — so beelink's
`folder_Luna_Faceswap.png` describes a folder that actually exists there. **This is still
an open operator call**; nothing is lost either way.

### Configs — decided per file, not per box

Four files diverged. `llm_runtime.json` went the **opposite way to the original guess**:

| file | winner | why |
| --- | --- | --- |
| `llm_runtime.json` | **M4** | M4 named `qwen3vl-abliterated` (the current M1 model, Aug 13 17:20); beelink named `huihui_ai/dolphin3-abliterated:8b` (Aug 11 18:01). beelink's own `OLLAMA_URL` points at the M1, and `/api/tags` there serves **only** `qwen3vl-abliterated` — beelink was pointed at a model its endpoint does not have. |
| `cloudflare.json` | beelink | newer, strict superset (adds `lora_bucket: me-lora-private`) |
| `atlas_cloud.json` | beelink | moves Luna from `minio://` to a matching `r2://me-lora-private/…`; self-consistent with the `cloudflare.json` key, so the pair must not be split |
| `characters.json` | beelink | adds `_batchtest` |

`llm_runtime.json` is now `7fa4914d…2f1fc5` on both boxes. Losing sides are archived on
beelink under `configs/_migration-20260814/` (`beelink-pre-overwrite/`, `m4-copies/`) —
nothing was discarded.

### Voice references

`/Users/williamlilley/Projects/pocket-voice/refs` →
`jellytot@192.168.50.2:/home/jellytot/me-lora-mounts/voice-refs`
(jarvis, joi, maya × 8 registers). **All 144 files byte-identical by sha256.** beelink has
one extra file, a deliberate `.gitignore` containing `*`.

Posture was preserved and tightened: dirs `700`, files `600`, zero group- or
world-readable files, outside every git worktree and every docker build context. The M4's
`jarvis/` was `755` and was brought to `700` to match `maya`/`joi`.

**The M4's copy of the refs must stay.** `pocket-voice` runs natively on the M4 and is
handed a *host* path — `.voice-register-choices.json` records
`host_path: /Users/williamlilley/Projects/pocket-voice/refs/maya/serious/01.wav`. beelink's
copy serves listing and auditioning in the UI; the M4's serves actual synthesis. They are
not redundant, and that path was deliberately **not** rewritten.

---

## 3. The voice route: SSH, not a cable listener

### Why not a listener on the cable

The obvious design — have pocket-voice listen on `192.168.50.1` so beelink can call it —
**does not work on this M4**, and fails in the worst possible way.

Measured 2026-08-13: an inbound listener bound to `192.168.50.1` **blackholes**. `lsof`
shows `LISTEN`, `curl` reports the connection established, the request is written, and
`accept()` never fires. The identical binary on loopback returns 200. It presents as an
application hang with no error anywhere to grep for. This is the macOS Local Network
privacy (TCC) model, which is enforced **per binary** — see the estate note on
`curl` → 200 vs `.venv/bin/python` → "No route to host".

Rebinding was rejected for a second, independent reason: **on this estate a `0.0.0.0`
listener is tailnet-wide.** pocket-voice can synthesise a specific real person's voice from
`voices/maya.safetensors`. It stays on loopback by deliberate decision.

### Why SSH works

`sshd` is Apple-signed, runs as root in the **system** launchd domain, and sits outside the
per-user Local Network TCC model entirely. Outbound from the M4 is unaffected too. So the
pattern is the one the presence bridge already uses: **beelink pulls over SSH**, and the
forward terminates on the M4's *own loopback*, creating **no new M4 listener at all**.

```
beelink 127.0.0.1:8911  ──ssh -L──►  M4 sshd  ──►  M4 127.0.0.1:8911 (pocket-voice)
        (loopback only)                cable 192.168.50.1, 0.62ms
```

Live command on beelink:

```
/usr/bin/ssh -N -T -o BatchMode=yes -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=20 -o ServerAliveCountMax=3 \
  -o StrictHostKeyChecking=accept-new \
  -L 127.0.0.1:8911:127.0.0.1:8911 williamlilley@192.168.50.1
```

This uses a **different key** from the presence bridge's — that one is `command=`-restricted
and cannot carry a port forward.

### Proof the voice service is not on the tailnet

Not asserted — measured, from a real tailnet peer:

```
M4    → beelink tailnet 100.113.51.76:8911/healthz   →  000   (no listener)
beelink host 127.0.0.1:8911/healthz                  →  200   {"ok":true,"cloning_available":true,…}
M4    lsof :8911  →  127.0.0.1:8911 (LISTEN)   — loopback only, not rebound
M4    lsof :8912  →  127.0.0.1:8912 (LISTEN)   — loopback only, not rebound
```

The forward binds `127.0.0.1` on beelink, so it is invisible to the tailnet **and** to every
other container on that shared build box.

### Known gap: the voice bridge stops at the host

The tunnel is reachable from beelink's **host**, but **not from the me-lora container**, and
the container is not configured to use it either. Three things are missing:

1. **`host.docker.internal` resolves to `172.17.0.1`** on beelink (the docker0 gateway, via
   `--add-host …:host-gateway`). The forward binds `127.0.0.1` only. A container connecting
   to `172.17.0.1:8911` therefore hits a 10s connect timeout.
2. **No `POCKET_VOICE_URL`, `VOICE_REFS_DIR` or `VOICE_REFS_HOST_DIR`** in beelink's
   container env. The M4's container had all three.
3. **No `voice-refs` bind mount.** `/api/voice/refs` returns
   `{"available":false, …"is not mounted in this container"}`.

Measured consequence — every other route is under 15ms:

```
/api/characters   200   0.009s
/api/gallery      200   0.014s
/api/voice/refs   200   0.011s   available:false
/api/health       200  10.06s    ← one 10s probe
/api/voice/state  200  20.21s    ← two 10s probes (pocket-voice + pocket-ears)
```

`/api/voice/state` reports
`ConnectTimeoutError(host='host.docker.internal', port=8911, connect timeout=10)`.
The LLM half of the same response is healthy: `qwen3vl-abliterated` on the M1.

**Remedy, when someone is ready to recreate the container.** Do *not* bind the forward to
`172.17.0.1` — that is the default bridge and would expose voice cloning to every container
on a box where foreign docker builds run. Bind it to the **`me-lora_default` gateway**,
`172.18.0.1`, whose only members are `me-lora-ui` and `me-lora-minio`:

```
ssh -N -T -o ExitOnForwardFailure=yes -o ServerAliveInterval=20 \
    -L 172.18.0.1:8911:127.0.0.1:8911 \
    -L 172.18.0.1:8912:127.0.0.1:8912 williamlilley@192.168.50.1
```

then recreate `me-lora-ui` with `POCKET_VOICE_URL=http://172.18.0.1:8911`,
`VOICE_REFS_DIR=/app/voice-refs`,
`VOICE_REFS_HOST_DIR=/Users/williamlilley/Projects/pocket-voice/refs` and
`-v /home/jellytot/me-lora-mounts/voice-refs:/app/voice-refs:ro`.
Note **`:8912` (pocket-ears) is not forwarded at all today** — that is the second of the two
10s timeouts.

**The tunnel is also not persistent.** It is a bare `ssh` process started by hand on
2026-08-13 21:16 with no systemd unit, no cron entry and no `autossh`. It will not survive a
beelink reboot. It needs a unit before it can be relied on.

---

## 4. What was removed from the M4, and what was not

### Removed

```
docker stop me-lora-ui me-lora-minio
docker rm   me-lora-ui me-lora-minio
```

Ports freed, confirmed with both `lsof` and `curl`:

```
127.0.0.1:8000  no listener   curl → 000
127.0.0.1:9000  no listener   curl → 000
127.0.0.1:9001  no listener
```

`com.melora.funnel` — a `KeepAlive` launchd agent running `tailscale funnel 9000` — was
booted out and its plist renamed `.disabled`. See §5; this one mattered.

### NOT removed — deliberately

- **All four volumes** — `me-lora_ui-configs`, `me-lora_ui-dataset`, `me-lora_ui-outputs`,
  `me-lora_minio-data`. A container is trivially recreatable and a volume is not. Deleting
  them is a **separate operator decision** to make once beelink has proven itself over a few
  days.
- **`me-lora-ui:latest`** (3.42GB image) — needed for rollback.
- **The empty `me-lora_default` network** — harmless, and needed for rollback.
- **`~/Projects/pocket-voice/refs`** — load-bearing for synthesis on the M4. See §2.
- **pocket-voice `:8911` and pocket-ears `:8912`** — still running, still loopback-only.
  These are the M4's job now.

---

## 5. What still referenced the M4's me-lora

| reference | status |
| --- | --- |
| **`com.melora.funnel` launchd agent** | **FIXED — and it was a live exposure.** It ran `tailscale funnel 9000`, publishing the M4's me-lora MinIO **to the public internet** (`/tmp/melora-funnel.log`: `Available on the internet: https://mac-mini-m4-pro.tailb4b671.ts.net/ \|-- proxy http://127.0.0.1:9000`). `KeepAlive`, 50 restarts, up 25h. Booted out with `launchctl bootout gui/$(id -u)/com.melora.funnel`; plist renamed `com.melora.funnel.plist.disabled`. Verified afterwards: `tailscale serve status -json` shows no `443` entry and `AllowFunnel: null`. |
| **beelink intranet SERVICES card** (`/home/jellytot/intranet.py:78-79`) | **No change needed.** It probes beelink's *own* `:8000` and `:9000`. It was already describing the surviving stack. |
| **`~/Projects/gen-pipeline/mcp-server/server.py:18`** | **Reported, not changed.** `BASE_URL = os.environ.get("ME_LORA_BASE_URL", "http://127.0.0.1:8000")` — the default now points at nothing. Not running and not registered as an MCP server anywhere. It also reads `UI_OUTPUTS_DIR` from a local path that no longer has data behind it. Fixable with `ME_LORA_BASE_URL`, but the right value depends on whether it should reach beelink over an SSH forward or the tailnet — an operator call. Its README line 4 ("same machine only") is now wrong. |
| **`~/handover-2026-08-13-infra.md:39,181`** | **Reported, not changed.** Lists `:8000 → me-lora` and `me-lora/docker-compose.yml:7` in the M4 port table. Now stale. Left alone — it is a dated handover, not live config. |
| `boltrig-familiar/familiar-hands`, `familiar-chat` (`:8000`) | **Not affected.** That `:8000` is the boltrig kernel, a different service. |
| `openreel/infra/transcribe-gpu/setup.sh` (`:8000`) | **Not affected.** Unrelated GPU transcribe box. |
| M4 me-lora source tree / compose file | **Does not exist.** There is no `~/Projects/gen-pipeline/me-lora` and no compose file on the M4; it ran purely from a prebuilt image plus named volumes. That is why rollback needs the captured inspect JSON. |

---

## 6. Rollback

Everything needed is intact: volumes, image, network. Config captured at
`/Users/williamlilley/me-lora-m4-retire-20260814/` — `m4-me-lora-ui.inspect.json`,
`m4-me-lora-minio.inspect.json`, `m4-images.txt`.

**Secrets are not in this document and not in that capture in usable form.** The M4
container carried `ME_LORA_PASSWORD`, `ME_LORA_SESSION_SECRET`, `ME_LORA_API_KEY`,
`CLOUDFLARE_*`, `HF_TOKEN`, `DEEPSEEK_API_KEY`. The inspect JSON does contain them in
clear — treat that directory as secret material. beelink's live container is the better
source: `docker inspect me-lora-ui --format '{{range .Config.Env}}{{println .}}{{end}}'`.

To restore the M4 stack:

```sh
# 1. network already exists; recreate if needed
docker network create me-lora_default 2>/dev/null

# 2. minio
docker run -d --name me-lora-minio --network me-lora_default --network-alias minio \
  --restart always \
  -p 127.0.0.1:9000:9000 -p 127.0.0.1:9001:9001 \
  -v me-lora_minio-data:/data \
  -e MINIO_ROOT_USER=minioadmin -e MINIO_ROOT_PASSWORD=<from inspect> \
  minio/minio:latest server /data --console-address :9001

# 3. ui  (env: copy the full list out of m4-me-lora-ui.inspect.json)
docker run -d --name me-lora-ui --network me-lora_default --restart always \
  -p 8000:8000 \
  -v me-lora_ui-configs:/app/gen-pipeline/me-lora/configs \
  -v me-lora_ui-outputs:/app/gen-pipeline/me-lora/ui/outputs \
  -v me-lora_ui-dataset:/app/gen-pipeline/me-lora/dataset \
  -v /Users/williamlilley/Projects/pocket-voice/refs:/app/voice-refs \
  -v /Users/williamlilley/Projects/gen-pipeline/ComfyUI/models:/app/gen-pipeline/ComfyUI/models \
  --env-file <(…) me-lora-ui:latest \
  uvicorn app:app --host 0.0.0.0 --port 8000
```

Two things to change if you do restore it:

- The original published `8000` on **all interfaces**. Use `-p 127.0.0.1:8000:8000`.
- Do **not** re-enable `com.melora.funnel`. It put the LoRA object store on the public
  internet. If the plist is ever restored from
  `~/Library/LaunchAgents/com.melora.funnel.plist.disabled`, read §5 first.

**Do not run both stacks at once against divergent volumes.** The whole point of this
migration was that the two copies had drifted; running both again recreates that problem.

---

## 7. Verification log (2026-08-14, after the M4 containers were removed)

```
beelink POST /login  williamlilley             → 303 + session cookie
beelink POST /login  wrong password            → 401
beelink GET  /api/characters  (no cookie)      → 401
beelink GET  /api/characters  (cookie)         → 200  5 characters
        _batchtest 2, Amara 0, Bella 21, Luna 74, Luna Cartoon 14
beelink GET  /api/gallery                      → 200  27033 bytes
beelink GET  /api/outputs/voice-20260813-172605-maya.wav → 200  766124 bytes
in-container sha256 .voice-register-choices.json → c392e622…eea16   (matches M4)
in-container count voice-20260813-*             → 8
beelink 127.0.0.1:8911/healthz                  → 200  cloning_available:true
M4      127.0.0.1:8000                          → 000  (freed)
M4      127.0.0.1:9000                          → 000  (freed)
```
