# Finding of fact: nobody can signal a per-cell-uid cell without a same-uid reaper

Recorded 2026-07-20 by Lexby, while implementing [2026] VJS-CC-VJS 7 J1. Not ordered by the court;
found by testing the design before building on it, and recorded because it changes the spawner's
shape and would otherwise have surfaced at J9 with two live cells and much less room to think.

## What I expected

That the API would drive a per-cell-uid cell exactly as it drives a cell today: spawn it, hold its
stdio, and terminate or kill it through the transport timeouts.

## What is actually true

Under the granted posture (`--user 0:0 --cap-drop ALL --cap-add SETUID --cap-add SETGID
--security-opt no-new-privileges:true`), tested directly:

| Actor | Action on a cell running as uid 20001 | Result |
|---|---|---|
| API (uid 10001) | `kill(SIGTERM)` | **EPERM** |
| API (uid 10001) | `waitpid` | **ECHILD** (not its child) |
| API (uid 10001) | `pidfd_open` | **succeeds** |
| Spawner (uid 0, no `CAP_KILL`) | `kill(SIGTERM)` | **EPERM** |
| Spawner (uid 0, no `CAP_KILL`) | `kill(SIGKILL)` | **EPERM** |
| Spawner (uid 0, no `CAP_KILL`) | `waitpid` | **succeeds** |

The API result is unsurprising: a different uid, and not its child.

**The spawner result is the one that matters, and I had it wrong.** Being uid 0 is not enough.
Signalling a process with a different uid needs `CAP_KILL`, and the grant is `SETUID` and `SETGID`
only. `cap_drop: ALL` means root here is root in name and not in the one respect this needs. So on
the pleaded design **no process in the container could terminate a runaway cell**: not the API, not
the spawner that forked it.

That is an operational hole (a spinning cell could not be stopped) and a security one (a cell that
declines to exit could not be removed), and it would have been discovered under J9 with two live
cells rather than here.

## The route that works, and needs no new capability

Same-uid signalling requires no capability at all. So to terminate a cell running as uid U, the
spawner forks a **reaper** which drops to uid U and signals from there. Proved:

```
same-uid reaper kill -> SUCCEEDED
cell reaped by spawner: True | signalled: 15
```

The spawner remains the parent, so it still `waitpid`s normally. The reaper exists only long enough
to deliver one signal and exit.

## What this changes

The spawner protocol needs lifecycle verbs, not just `spawn`:

- **spawn** - as built.
- **terminate / kill** - fork a same-uid reaper, signal, exit. The API asks; the spawner decides,
  on the same validate-do-not-obey rule as spawning (it will only signal a pid it actually spawned,
  and only with SIGTERM or SIGKILL).
- **wait** - the spawner `waitpid`s. The API can additionally hold a `pidfd` to observe exit
  without asking, which is useful because it needs no round trip and cannot be starved by a busy
  spawner.

## Why it is recorded rather than just fixed

Two reasons. It is a fact about the deployment that the next person will otherwise rediscover the
hard way, and it is a case where the design I had already pleaded to the court was incomplete in a
way the court did not catch either. The judgment conditions the grant on privilege separation and
says nothing about lifecycle, because neither of us thought about termination. That is worth having
on the record before the two-cell gate, not after.

**It does not require going back to the court.** No new capability is sought; the same-uid reaper is
built entirely from `SETUID`, which is already granted, and it makes the posture no wider.
