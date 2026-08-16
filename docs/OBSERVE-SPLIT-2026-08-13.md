# The observer split: Boltrig captures, a character interprets

**Date:** 2026-08-13
**Box:** M4 (`mac-mini-m4-pro`) only. Nothing left the machine except the frames
the loop already sent to the M1's VLM, over the path it already used.
**Phase:** 3 of `~/.claude/plans/swirling-zooming-sundae.md`.
**Status:** split done, live, and verified against the real camera. Uncommitted
and awaiting review.

---

## 1. Why this was not tidying

`~/Projects/companion-observer/observe.py` ran the flow **backwards**. At v1
lines 123-131 the raw frame was written to `FRAMES_DIR` and `REF_DIR` only
inside:

```python
if "NOTHING_OF_NOTE" not in text:
    ...
    subprocess.run(["cp", cur, f"{FRAMES_DIR}/{now:%Y%m%d-%H%M%S}.jpg"], check=True)
```

One character's prose decided whether the pixels survived.

`docs/SPEC-character-bundle.md` promises:

> Boltrig captures **what was seen**; the character decides **what that means for
> it**. Two characters watching the same frame may legitimately end up in
> different emotional states, and neither is wrong.

That was **unimplementable** in v1, not merely unimplemented. By the time
anything reached disk, one character's reading had already been applied and the
alternative was gone — a second character installed tomorrow would have nothing
to disagree about, because the frames its predecessor found unremarkable were
never written. The archive-ordering fix is the precondition for per-character
emotion, which is why this had to land before any bundle work.

The infrastructure was also already **unowned**, and the copies had drifted:

| where | what it said | truth |
| --- | --- | --- |
| `presence.py:41` | `DARK_MEAN = 12.0  # matches observe.py's lens-covered threshold` | hand-copied |
| `presence.py:39-40` | a second `mean_diff`, numpy, differently tuned | duplicate |
| `presence.py:43-44` | "observe.py's own frame buffer … still 72h" | **false** — it moved to 24 |

A comment asserting agreement is not a mechanism for it.

## 2. The seam

The governing decision, from the spec: **the daemon is always Boltrig's, whoever
is watching.** Jarvis, Maya or Bella — same loop, same retention, same quiet
hours, same stop gesture. Only the prompt and where the interpretation lands
vary. So **a bundle ships configuration, never executable code.**

| file | owner | holds |
| --- | --- | --- |
| `capture_policy.py` *(new)* | Boltrig | `THUMB`, `DARK_MEAN`, `CHANGE_THRESHOLD`, `STATIC_DIFF`, `INTERVAL`, `DARK_PAUSE_S`, `GESTURE_PAUSE_S`, `QUIET_START/END`, `RETENTION_H`, and the thumbnail/mean/diff primitives |
| `capture.py` *(new)* | Boltrig | `grab()`, archival, the observation record, `withdraw()`, `prune()` |
| `character.py` *(new)* | Boltrig | loads bundle config, calls the VLM, writes the bundle's diary, enforces what a bundle may not decide |
| `characters/maya.json` *(new)* | **the bundle** | the prompt, `diary_dir`, `skip_markers`, `max_tokens`, `temperature` |
| `observe.py` *(rewritten)* | Boltrig | the loop and the three pauses; unchanged launchd entrypoint |

`app.companion.observer` still runs `observe.py` with the same interpreter and
the same log. The plist was not touched.

## 3. The order-of-operations fix

```
grab ─> not quiet? not dark? diff >= CHANGE_THRESHOLD?
          │
          ├─ archive()  frame + day reference + observations.jsonl row   <── COMMITTED HERE
          │
          └─ ask every character ─> diaries
                   │
                   └─ withdraw()  the ONLY path back, and it only deletes
```

`capture.archive()` runs on capture's own criteria and commits before any
character is asked. Interpretation is downstream and cannot reach back except
through `capture.withdraw()`.

Two consequences fell out of that:

- **The day reference no longer depends on a character.** It used to be created
  only inside the "notable" branch, so a quiet morning produced no reference at
  all.
- **A stop gesture suppresses the moment for every character.** All characters
  are asked, *then* diaries are written — otherwise whoever was asked first would
  record a frame the operator was in the act of waving off. The gesture frame,
  its day reference and its observation row are withdrawn, then
  `GESTURE_PAUSE_S`. **Nothing clears a gesture pause.**

## 4. Three things a bundle cannot do

Enforced in `character.py`, not trusted to the JSON:

1. **Disable the stop gesture.** `GESTURE_CLAUSE` is appended to every prompt by
   Boltrig and the response is scanned by Boltrig. With zero characters
   configured, capture still runs and `gesture_check()` asks Boltrig's own
   minimal question — so the policy is never absent.
2. **Name a host or model.** `VLM_URL` / `VLM_MODEL` are operator configuration
   in `character.py` (the `1b69ec8` M1 repoint, comment carried over verbatim).
   A downloaded character cannot point this camera at somebody else's server.
3. **Write outside the store.** `_diary_dir()` resolves and refuses anything
   outside `store/personal`.

## 5. One source of truth for the drifted constants

`~/pixy-stream/presence.py` no longer restates anything:

```python
sys.path.insert(0, os.path.expanduser("~/Projects/companion-observer"))
import capture_policy as policy
...
RETENTION_H = policy.RETENTION_H
t = policy.thumb(jpg)
if policy.is_dark(t): ...
static = policy.is_static(t, last_thumb)
```

`STATIC_DIFF`, `DARK_MEAN`, `THUMB` and the numpy `mean_diff` are gone, and so is
the false 72h comment. `numpy`, `PIL` and `io` became unused there and were
dropped. The README's flow diagram carried the *same* 72h drift plus a stale
`localhost:8100`; both corrected, and it now names the constant rather than a
number.

**Still a copy, honestly:** `camerad.py:46`
`CURRENT_INTERVAL = 30  # observe.py's INTERVAL`. Left alone deliberately —
camerad holds the camera behind a fails-closed interlock whose recovery is a
physical replug, and it is not worth a restart for a constant. Noted in
`capture_policy.py`'s docstring for whoever touches camerad next.

## 6. Verification actually run

**Parity against committed v1** (`git show HEAD:observe.py`, functions exec'd
side by side with the new modules):

| check | result |
| --- | --- |
| composed prompt (`bundle prompt + GESTURE_CLAUSE`) vs v1 `PROMPT` | **byte-identical** |
| all 9 thresholds + `VLM_URL` + `VLM_MODEL` | **identical** |
| `frame_mean` v1 vs `policy.mean` on a real frame | 85.177978515625 both |
| `mean_diff` v1 (PIL/sum) vs `policy.mean_diff` vs presence's old numpy form | 29.6279296875 all three |

**Diary path escape** — `~/.ssh`, `../../../../etc`, `/tmp/elsewhere` all
REFUSED; a path inside the store accepted.

**Deterministic ordering trial** against a scratch store, on the live camera
frame, with two bundles installed:

```
[1] archive first          frame on disk + day reference + jsonl row, no character consulted
[2] forced NOTHING_OF_NOTE diary NOT written; frame STILL on disk; row STILL present
[3] two characters         bella kept=True  -> diary-bella
                           maya  kept=False -> nothing
    (same stored frame, divergent outcomes — the thing v1 could not do)
[4] withdraw               frame gone, day ref gone, 0 rows left, diaries untouched
```

**The shipped entrypoint, run for real.** `observe.py` itself, against a scratch
store with one bundle installed, on the live camera frame and the real M1:

```
[21:24] watching for: Bella -> .../loop-store/diary-bella
[21:24] bella: keyboard, water bottle, microphone, whiteboard, door, eyeglasses, vape device
```

and on disk: `frames/20260813-212441.jpg`, `reference/2026-08-13.jpg`,
`observations.jsonl`, `diary-bella/2026-08-13.md`. Archive → record → interpret →
diary, through the loop that launchd runs.

**Live proof on the running daemon**, after the 21:05 restart onto the split
code. Four frames archived in twelve minutes, and the diary disagrees with the
archive in exactly the way it is supposed to:

| time | frame archived | jsonl row | diary line |
| --- | --- | --- | --- |
| 21:14:10 | yes, 62,606 B | yes | **no** |
| 21:20:29 | yes, 59,882 B | yes | **no** |
| 21:24:48 | yes | yes | yes |
| 21:25:45 | yes | yes | yes |

The two frames with no diary line are the whole point. The room was empty and the
kitchen light was off — Maya had nothing to say, and the frames survived anyway.
**Under v1 neither would ever have been written to disk.** Both stdout and stderr
land in `logs/observe.log` with `flush=True` and the log holds no error, so those
are `NOTHING_OF_NOTE` skips rather than swallowed failures; re-sampling
`20260813-211410.jpg` against the M1 returns `NOTHING_OF_NOTE` in roughly 1 of 5
draws at temperature 0.3, consistent with what the daemon recorded.

**Pre-existing, and NOT caused by the split — the stop gesture is unreliable at
the model layer.** Both 21:24 and 21:25 diary lines describe "an open palm toward
the camera" in prose without the model emitting `STOP_WATCHING`, so no pause
fired. v1 did the same thing at 18:04 today, before any of this work:

> `- 18:04 … his right arm is extended forward, holding an open palm toward the
> camera as a stop signal.`

— written to the diary as prose rather than treated as a gesture. The prompt is
byte-identical across the split, so the split neither caused nor fixed it. It is
worth its own attention: the gesture is enforced structurally (Boltrig appends
the clause and scans the reply) but the *recognition* depends on the model
choosing the sentinel over description, and it does not do so reliably.

**Services.** `app.companion.observer` pid 63205 (started 21:05:38, after the
files were written) and `app.pixy.presence` pid 61949 both alive; presence
publishes to `presence.jsonl` with `reused: true/false`, i.e. `policy.is_static()`
working. `app.pixy.camerad` pid 62465 has run since 16:10 and was not restarted.

**No new network surface.** `lsof -nP -iTCP -sTCP:LISTEN` shows neither the
observer nor presence owning any listening socket. 8896/8899/8900 are camerad
(pre-split), 8911/8912 pocket-voice and its STT; everything else predates the
work.

## 7. What remains

- **Nothing is committed.** `git status` in `companion-observer` shows
  `M observe.py`, `M README.md` and untracked `capture.py`, `capture_policy.py`,
  `character.py`, `characters/`. Another session's `pixy-ptz`, `pixy-ptz.m`,
  `pixy-ptz.bak` are untouched and must not be swept in.
- **`~/pixy-stream` is not a git repo**, so there is nothing to diff against.
  `presence.py.pre-split` was left beside it, reconstructed by reversing the
  edits; review with `diff -u presence.py.pre-split presence.py`, then delete it.
- **camerad still hand-copies `INTERVAL`** (§5). One import when it is next
  touched for another reason.
- **The services are still Maya's launchd jobs.** `app.pixy.camerad`,
  `app.companion.observer`, `app.companion.vigil`. The *code* seam is now correct;
  the ownership move into Boltrig — a UI toggle, device selection, observations
  and settings persisted to the kernel, and an honest refusal when the user has
  the camera off — is the rest of Phase 3 and is not done.
- **Nothing reads `observations.jsonl` yet.** It is the record a character is
  meant to interpret, but `consolidate.py` still reads the diary. Until a reader
  exists, per-character emotion is *possible* rather than *present*.
- **Familiar and Jarvis have no bundle.** Only `characters/maya.json` exists.
  Familiar omits phenotype and emotion entirely; the loop is now indifferent to
  that, which is the point.
- **Emotion state does not persist anywhere.** The spec's open question — whether
  emotion travels with a bundle to another Boltrig — is untouched and still needs
  deciding deliberately.

## 8. Two decisions for the operator

- **Archive volume rises.** Frames now land on `changed` alone rather than
  `changed AND notable`. The buffer is 11 MB / 168 files over 24h today; the
  delta is only the frames a character called unremarkable, worst case ~180 MB/day
  against 104 GB free. Cheap, but it is a real increase in how much of the room
  sits on disk.
- **`observations.jsonl` rows expire with their frames.** `prune()` drops rows
  whose images are gone, because keeping them would quietly convert a 24h
  retention window into a permanent index of when the room was occupied. Say if
  the record should outlive the pixels.
- **A VLM outage now leaves uninspected frames.** In v1 an exception meant
  nothing was archived; now the frame is committed before the call, so a
  sustained outage fills the buffer with frames no gesture check ever saw. They
  still expire at `RETENTION_H`, and the alternative is losing the moment
  entirely — but it is a change in posture worth knowing about.
