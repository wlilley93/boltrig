# Handover — unattended build, 2026-08-13

Written 18:10 BST while the operator was out, against the approved plan
`~/.claude/plans/swirling-zooming-sundae.md`.

Every claim below was re-verified on the machine named at the time of writing —
I did not trust the reports handed to me by the earlier phases of this run, and
in two places they were wrong or absent. Commands and outputs are quoted
verbatim. Where a step was not done, it says so.

> **A sibling document exists.** Another session wrote
> `docs/HANDOVER-2026-08-13-unattended-run.md` at 18:00, covering overlapping
> ground. We agree on the headline (the exposure is open). This document adds
> the sequencing hazard in §2 and the spec findings in §6. Read this one for
> what to do next; that one for its own narrative.

---

## 1. SECURITY OUTCOME: the `:8901` exposure is **NOT closed**

**No. It is open right now, exactly as it was when the plan was written.**

Verified from the M4, which is a peer of beelink — never from beelink itself, a
serve tested from its own host returns 000 and looks broken:

```
$ curl -s -o /dev/null -w "REMOTE_HTTP=%{http_code}\n" https://beelink.tailb4b671.ts.net:8901/remote
REMOTE_HTTP=200

$ curl -s https://beelink.tailb4b671.ts.net:8901/remote | wc -c
   62152
```

That is the full Maya player UI (`<title>Maya</title>`), served to every device
on the tailnet with no token, no credential and no redirect.

The mount is still in place on beelink:

```
$ tailscale serve status
...
https://beelink.tailb4b671.ts.net:8901 (tailnet only)
|-- / proxy http://192.168.50.2:8901
```

and the tailnet listeners still sit beside the app's own cable bind, with no
owning user because they belong to tailscaled:

```
$ ss -ltnp | grep 8901
LISTEN 0 5       192.168.50.2:8901  users:(("python",pid=2236343,fd=3))
LISTEN 0 4096   100.113.51.76:8901
LISTEN 0 4096   [fd7a:115c:a1e0::2432:334c]:8901
```

### Neither branch of the plan was taken

The plan offered a proxy (preferred) or dropping the mount (honest fallback,
card reverts to non-clickable). **Neither happened.** This is not the
"proxy failed, so we removed the mount" case — there is nothing to explain
away, and the card is still clickable precisely because nothing was done.

- **The proxy does not exist.** On beelink, `grep -n "8901\|/remote" ~/intranet.py`
  returns only the service-card row, line 56:
  `("Studio", "Maya player", 8901, "/remote", "Clip player + haptics remote", True)`.
  There is no proxy route. The trailing `True` still marks it externally
  linkable, so the intranet card continues to link straight past the gate to the
  tailnet origin — the exact behaviour the plan set out to remove.
- **The mount was not dropped either.** It is quoted above, still live.

The player is a bare process, not a unit — `/proc/2236343/cmdline` is
`/home/jellytot/Projects/maya-remote/.venv/bin/python maya_player.py --host 192.168.50.2 --port 8901`,
cwd `/home/jellytot/Projects/maya-remote`. There is no systemd unit for it
(`systemctl list-units | grep -i maya` → nothing), so a rebind to loopback is a
manual restart, and a reboot loses the player entirely.

The `--host 192.168.50.2` bind is **correct and should not be "tidied"**. The
cable bind is the design. The hole is the tailscale serve mount sitting beside
it, and that is the only thing that should be removed.

---

## 2. The hazard that matters more than the exposure itself

**Fixing presence before closing `:8901` converts a UI-shell exposure into a
full personal-data exposure, in one step, silently. Do not do it in that order.**

Right now every privacy-gated endpoint on the exposed player refuses:

```
$ curl -s https://beelink.tailb4b671.ts.net:8901/api/awareness
{"him": false, "present": false, "withheld": true, "reason": "no presence detector"}

$ curl -s https://beelink.tailb4b671.ts.net:8901/api/memory
{"known": false, "withheld": true, "reason": "no presence detector"}

$ curl -s https://beelink.tailb4b671.ts.net:8901/api/vigil
{"withheld": true, "reason": "no presence detector"}
```

That `withheld: true` is **a bug, not a gate.** It is the fail-closed branch of
`~/Projects/maya-remote/identity.py` on beelink:

```python
30: VERDICTS = os.environ.get("PRESENCE_VERDICTS") or os.path.expanduser(
31:     "~/pixy-stream/logs/presence.jsonl")
...
56:         return {"him": False, "age_s": None, "reason": "no presence detector"}
```

`~/pixy-stream/logs/presence.jsonl` does not exist on beelink —
`ls` returns `No such file or directory`, exit 2 — because pixy-stream lives on
the M4. `PRESENCE_VERDICTS` is unset in the player's environment
(`tr '\0' '\n' < /proc/2236343/environ | grep -i presence` → empty).

So the broken presence bridge is currently the **only** thing withholding the
diary, the fact sheet and the vigil photographs from every tailnet device.
Task #4 ("fix the presence-to-player coupling") and task #5 ("close the :8901
exposure") are coupled, and the plan does not say so. **Close #5 first.**

### The plan's severity line is stale, in the safe direction

The plan says the mount "publishes 5.5 GB of intimate media to every tailnet
device". On beelink it does not, today:

```
$ du -sh ~/Projects/maya-remote
50M	.

$ curl -s https://beelink.tailb4b671.ts.net:8901/api/clips
{"set": "", "clips": []}
```

The checkout is 50 MB and carries no media — the 5.1 GB of clips stayed on the
M4, per the plan's own open decision #3. What leaks today is the player shell,
`/api/state` (`{"outfit": null, "set_scene": "studio", ..., "char": "Maya"}`)
and an empty clip list. That is a real exposure and it still must close, but the
urgency is "before either presence or the media follows the player across", not
"5.5 GB is on the wire right now".

---

## 3. What was actually completed and verified

### Phase 1.2 — observer repoint: **done**, including the half the plan left open

The plan's outstanding item was that `observe()` still hard-coded
`"model": "qwen3-vl"` in the request body. It no longer does:

```python
28: VLM_URL = os.environ.get("VLM_URL", "http://mac-mini-m1:11434/v1/chat/completions")
30: VLM_MODEL = os.environ.get("VLM_MODEL", "qwen3vl-abliterated")
71:     body = json.dumps({"model": VLM_MODEL, "messages": [...
```

And it is writing diary entries for real, not merely exiting 0 — the log was
being appended to while I was reading it:

```
$ tail -1 ~/Projects/companion-observer/logs/observe.log
[18:03] A man with a beard and glasses stands shirtless in front of a desk, looking down
at something off-camera. ... Nothing of note.
```

`app.companion.vlm` remains parked as `.disabled`. It was not restarted, which
is correct — restarting it would re-create the memory contention the M1
consolidation just cleared.

### Phase 1.3 — presence: **restored on the M4 only**

The plan recorded presence as absent from `launchctl list` entirely. It is now
loaded and running:

```
$ launchctl list | grep -i -E "presence|camerad|vigil|observer"
62465	0	app.pixy.camerad
82630	0	app.pixy.presence
83524	0	app.companion.vigil
80729	-15	app.companion.observer
```

and producing fresh verdicts every 8 s:

```
$ tail -1 ~/pixy-stream/logs/presence.jsonl
{"type": "presence", "dark": false, "known": false, "faces": 0, "unknown": 0,
 "best": null, "ts": 1786640712.3179781, "reused": false}
```
(file mtime 18:05, 1.75 MB)

**This does not reach the player.** Presence publishes to camerad's loopback bus
at `127.0.0.1:8900` and appends to the M4-local JSONL. The consumer, `identity.py`,
is on beelink. Half the job is done; the bridge is §5.

### Phase 4 — Familiar as a bundle: **done**, and I re-ran the gates myself

```
$ cd ~/Projects/boltrig/apps/worker && node_modules/.bin/tsc --noEmit -p tsconfig.json
VERIFY_TSC_EXIT=0        (no output)

$ node_modules/.bin/vitest run --reporter=dot \
    apps/worker/tests/familiarBundle.test.ts apps/worker/tests/characters.test.ts \
    apps/worker/tests/familiarStage.test.tsx
 Test Files  3 passed (3)
      Tests  30 passed (30)
```

The shader survived the move into the bundle root byte-for-byte, and the
manifest's declared digest matches the file on disk:

```
$ shasum -a 256 apps/worker/src/bundles/familiar/familiar.frag
aca897f206388b84ac93cbf8debb1181d8c3fda5e54939a487be65b8dde70035

$ grep -n sha256 apps/worker/src/bundles/familiar/character.json
16:      "sha256": "aca897f206388b84ac93cbf8debb1181d8c3fda5e54939a487be65b8dde70035"
```

The public-graph rule held: `characterPlugins.ts`, `apps/worker/package.json`
and `manifest.yaml` are untouched, so a clean clone still builds with the plugin
join empty. Familiar renders from a bundle with no phenotype and no prompts,
which was the whole point of doing her before Maya — and it paid off, see §6.

---

## 4. Broken or unverified

**Two failures I was handed are no longer real. I re-ran both and they pass** —
another session evidently fixed its files and re-captured while this run was in
progress. Recording the correction because the earlier phase reported them as
broken and that report is wrong:

- `apps/worker/tests/visual/manifest.test.ts` — reported failing. Now
  `Test Files 1 passed (1) / Tests 22 passed (22)`, exit 0.
- `apps/worker/scripts/check-structure.mjs` — reported failing. Now exit 0:
  `PASS: no new Worker structural debt and every ratchet matches current source.`
  (`files=163 functions=3790 debt_files=64`,
  `trusted_baseline=51e2bd67b7a67f645f7276de49277f73657aa41a`)

The full worker suite is currently **green**:

```
$ node_modules/.bin/vitest run --reporter=dot
 Test Files  84 passed (84)
      Tests  746 passed (746)
```

Genuinely outstanding:

- **`scripts/check_familiar_shader.sh` exits 2**, `NOT CHECKED: no upstream
  familiar.frag at ~/Projects/beelink-desktop/familiar/familiar.frag`. That is
  the script's designed behaviour on a box without that checkout, unchanged by
  the move — it still reports the same vendored digest.
- **Nothing is committed.** HEAD is `20eb6e8`. `git status --porcelain` shows
  ~40 modified paths and a large untracked set, most of it other sessions' work
  interleaved with the bundle's. Anyone reviewing should re-run the gates rather
  than trust any snapshot, including this one.
- **The tree was edited underneath this run.** Files authored by the bundle
  phase were modified mid-task by another actor, and
  `apps/worker/tests/desktopEnrollment.test.ts` was deleted while it worked. The
  worker typecheck was *not* green at the start of the run (exit 2, two TS2305
  errors from another session's uncommitted `desktop.ts` edit removing exports
  HEAD still has); it is green now only because that session deleted the test.
  The brief's claim that `tsc` was green beforehand was wrong.

---

## 5. Not done, and why

- **Phase 2 in full** — the proxy, the mount removal and the loopback rebind.
  This is a destructive, hard-to-reverse change to the shared box's network
  surface, on a service with no systemd unit to restart it, and the plan itself
  says "say the word: do the proxy". The word was not given before the operator
  left. Getting it wrong strands the player unreachable from the phone with
  nobody present to fix it. It is the top item waiting.
- **Phase 3** (camerad / presence / observer into Boltrig) — not started. It is
  architecture and it keeps; it also depends on decisions in Phase 2.
- **Phase 5** (judge Maya's voice by ear, then barge-in) — not started, and
  **not startable unattended by definition**: the deciding question is whether
  `/tmp/maya_pocket.wav` sounds like Maya, which requires a human ear. No amount
  of further benchmarking settles it; speaker similarity is Pocket TTS's weakest
  metric while its WER is best-in-class, so the numbers point the opposite way
  to every question already answered.
- **The presence-to-player bridge** (§2) — deliberately left undone. It would
  have opened the diary to the tailnet. The seam is already there when you want
  it: `identity.py` honours a `PRESENCE_VERDICTS` env override, so the fix is a
  path or a feed, not a code change. **Close `:8901` first.**

---

## 6. The Familiar bundle exposed four flaws in the spec

This is the most valuable output of the run. `docs/SPEC-character-bundle.md` was
written against Maya, and building the character who has *least* was the test of
whether it had smuggled in assumptions. It had.

**1. `prompts` cannot be required.** The spec's required triple is
`{id, display name, prompts}` and **neither shipped character has prompts**.
`apps/worker/src/character.ts` states the contract outright: *"this value is not
sent in Chat requests and does not alter response prose or dispatch"*. Familiar
and Jarvis are **bodies, not personas**. Requiring prompts would have forced the
invention of a persona for a character that has none — exactly the smuggled
assumption Familiar exists to catch. The missing axis: a character has a **body**,
and *optionally* a voice/persona. Maya is body + persona; Familiar is body only.
The schema makes `prompts` optional and says why in the field description.

**2. `blurb` is required by the registry but absent from the spec's required
list.** `sdks/web/src/characters.ts` `registerCharacter` throws on a missing or
unsafe blurb (1–240 chars, trimmed, no control characters). A bundle carrying
only the spec's required triple **cannot be installed**. Demonstrated by
validating `{schemaVersion, id, name, prompts}` against the schema:

```
["'blurb' is a required property",
 "'type' is a required property",
 "'visual' is a required property"]
```

**3. "A character with only prompts and a fallback voice id is a valid
character" is false in this registry.** `Character.render` is mandatory, so a
bundle with no `visual` has no body and cannot be put on the Stage. Either the
registry needs a bodiless character that falls back to the default Stage, or the
spec should stop claiming it.

**4. "A shader character has nothing to have a phenotype of" is wrong as
written, and the word is doing two jobs.** `boltrig/models/familiar.py`
`derive_familiar_genotype()` derives her body, palette, markings and accessories
by sha256 of the agent capability **name** — host data flowing kernel → character,
the reverse of the spec's stated direction. So a shader character *does* have a
phenotype-shaped thing. Split the word:

- **(a) does this character READ the host's measured affective state** — a
  consumption declaration. Familiar: **false**. Encoded as `phenotype.reads`.
- **(b) does it HAVE an appearance state of its own that travels.** Familiar:
  **non-empty**, but host-derived and therefore not bundle data. Left unmodelled.

What Familiar actually lacks is a *reading of the appraisal engine*, not an
appearance.

### One tension worth arguing about, not silently resolving

**"A bundle ships configuration, never executable code" versus "type: shader —
the bundle brings the fragment shader".** `familiar.frag` is 121 KB of GLSL. It
is a program. The rule survives only because GLSL is a pure function of its
uniforms inside a sandboxed GPU pipeline with no filesystem, no network and no
camera — it cannot do the thing the rule exists to prevent. But it *can* hang the
GPU and it *can* be a denial of service. **Restate the rule as "no
host-privileged code", not "no code"**, or the first person to read it literally
will conclude shader characters are illegal.

### The largest remaining gap

Familiar's inner life is character-specific **behaviour** that lives as **code**
in Boltrig's renderer, not as data in her bundle — the wandering mood baseline
and its tau, the ambient gesture envelope and its ids, the aperture entrance
timing, the per-mode composition numbers, all in `FamiliarWebGLRenderer.ts`. The
manifest can only *name* the model (`"autonomous-wander"`), which the canvas
source must declare it implements. **A second shader character cannot bring a
different inner life as configuration today.** This is the same seam the spec
drew for `observe.py`, unresolved one layer up.

### Two smaller notes

- **The manifest's `sha256` is a build/test-time gate, never a runtime one.**
  The loader runs in a browser with no filesystem and the shader arrives as a
  Vite `?raw` string. A format that implies runtime integrity checking would be
  overpromising.
- **"Where do bundle assets live" is resolved by force: inside `apps/worker/src`.**
  `apps/worker/Dockerfile` copies only `sdks/web/src`, `apps/worker/src` and
  three design-token files. A repo-root `bundles/` directory would simply not
  exist in the shipped image. Any bundle-on-disk decision has to survive that
  `COPY` list.
- **Familiar does not test "does emotion travel".** Her mood derives from nothing
  about the user, so her manifest says `travels: false` and there is nothing to
  gate. **Maya is the case that decides it.**

---

## 7. Rollback paths

Nothing in this run needs rolling back — the destructive work was not done. These
are the restore points that exist, including ones inherited from earlier today.

**beelink — `~/intranet.py`** (unmodified by this run; newest backup is from
15:45, before it):

```
intranet.py.bak-20260813-1544     9139 B   Aug 13 14:12
intranet.py.bak-20260813-maya    34444 B   Aug 13 15:45   <- closest to current
intranet.py.bak-pre-containers   11864 B   Aug 13 14:44
intranet.py.bak-pre-flags        33792 B   Aug 13 15:17
intranet.py.bak-pre-harden       24512 B   Aug 13 14:52
intranet.py.bak-pre-unixsock     31893 B   Aug 13 15:06
```
Current `~/intranet.py` is 34530 B. Restore with `cp`, then
`sudo systemctl restart beelink-intranet`.

**beelink — the tailscale serve mount.** Unchanged, still live. When Phase 2 is
done, the mount is removed with `sudo tailscale serve --https=8901 off` and
restored with `sudo tailscale serve --bg --https=8901 http://192.168.50.2:8901`.
**I ran neither — both are stated from the current `serve status` output, not
from execution.** Every serve edit needs `sudo` now that the unix-socket mount
exists, and note a serve can block its own backend from restarting.

**beelink — the player process.** pid 2236343, started by hand, no unit. If it
is killed, restart with
`cd ~/Projects/maya-remote && .venv/bin/python maya_player.py --host 192.168.50.2 --port 8901`.
There is nothing to restore it automatically.

**M4 — parked launchd plists.** Rename to restore:
- `~/Library/LaunchAgents/app.companion.vlm.plist.disabled` — parked **by
  decision**; restoring it re-creates the memory contention the M1
  consolidation cleared. Do not restore casually.
- `~/Library/LaunchAgents/app.maya.player.plist.removed-20260813` — the M4's own
  player, booted out when the player moved to beelink.

**M4 — crontab.** `~/crontab.bak-20260813-llmhost`, taken before the
`LLM_HOST` / `LLM_MODEL` repoint.

**boltrig — the bundle work.** Nothing is committed, so it reverts with
`git checkout --` on the modified paths plus deleting the untracked ones. Be
careful: the working tree is shared with several other sessions' uncommitted
work, so a blanket `git checkout .` or `git clean -fd` would destroy theirs too.
The bundle's own paths are:

```
 M apps/worker/src/components/characters.ts
 M apps/worker/src/components/familiar/FamiliarWebGLRenderer.ts
 R apps/worker/src/bundles/familiar/familiar.frag
 M apps/worker/tests/familiarStage.test.tsx
 M scripts/check_familiar_shader.sh
 M sdks/web/src/index.ts
?? apps/worker/src/bundles/
?? apps/worker/src/components/characterBundle.ts
?? apps/worker/tests/familiarBundle.test.ts
?? schemas/character-bundle/
?? sdks/web/src/characterBundle.ts
```

---

## 8. Suggested order on return

1. **Close `:8901`** — proxy route in `~/intranet.py`, then drop the mount, then
   rebind the player to loopback, then re-verify from the M4. Never from beelink.
2. **Then** bridge presence to the player (§2). Not before — the order is the
   difference between a UI leak and a diary leak.
3. Give the player a systemd unit while you are in there; it currently survives
   nothing.
4. Decide the four spec points in §6 before Maya's 22 GB is consolidated
   against the format.
5. Commit the bundle work, once the tree stops moving.
