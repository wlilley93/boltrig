# Finding of fact: CODEX_HOME writability and the no-capability routes to G3

Ordered by [2026] VJS-CC-VJS 6 directives H1 and H2. Recorded 2026-07-20 by Lexby.

The court refused my application for `CAP_SETUID`/`CAP_SETGID` and found that I had tested only
whether a hostile `config.toml` could be NEUTRALISED, never whether it could be made IMPOSSIBLE. It
identified an untested route (Option E: one root-owned, mode-0555 CODEX_HOME on the read-only image
mount, shared by every cell, with every per-cell value on argv) and ordered it tested before any
re-application. These are the findings, filed whichever way they came out, as the order requires.

All experiments used the pinned Codex 0.144.3 binary and reproduced the deployed container posture:
`--user 10001:10001 --read-only --cap-drop ALL --security-opt no-new-privileges:true`, with a
`/tmp` tmpfs and CODEX_HOME bind-mounted read-only.

## Finding 1: config LOADS under a read-only, foreign-owned CODEX_HOME

`codex doctor --json` with `CODEX_HOME` on a read-only mount reports `"config.load": "status": "ok"`
and emits only a warning:

```
WARNING: proceeding, even though we could not create PATH aliases: Read-only file system (os error 30)
```

This confirms the court's own observation, and it is the part of Option E that works.

## Finding 2 (decisive): the App Server does NOT run under a read-only CODEX_HOME

This is the fact H2 asked for, and it disposes of Option E in its pure form.

Boltrig's actual invocation is `app-server --listen stdio:// --strict-config`. Driven with an
`initialize` request under a read-only CODEX_HOME it fails at startup:

```
Error: failed to initialize sqlite state runtime under /opt/boltrig/codex-home:
failed to initialize state runtime at /opt/boltrig/codex-home
```

`codex exec` fails equivalently and earlier:

```
Error: failed to initialize in-process app-server client: Read-only file system (os error 30)
```

So Codex 0.144.3 requires a WRITABLE CODEX_HOME. It maintains sqlite state there. Where its session
and history writes land is therefore answered: inside CODEX_HOME, which is precisely the directory
Option E proposed to make unwritable. There is no observed fallback to `HOME` or `TMPDIR`.

## Finding 3: the sticky-bit hybrid gives nothing under a shared uid

The natural repair for Finding 2 is a CODEX_HOME that is writable for scratch but whose
`config.toml` cannot be replaced: a foreign-owned directory with the sticky bit (mode 1777) holding
a foreign-owned 0444 `config.toml`. The sticky bit restrains deletion to the file's owner.

This does not help here, for two independent reasons:

1. Every cell runs as uid 10001, so the sticky bit restrains no cell from touching another cell's
   file: they are all the same owner. Sticky separates uids, and we have one uid.
2. Creating a foreign-owned `config.toml` inside a per-cell directory the kernel makes at uid 10001
   would itself require `CAP_CHOWN`, which is the same class of grant the court refused.

## Finding 4: unprivileged user namespaces are unavailable, so no per-cell namespace route

A per-cell mount or user namespace would give a kernel-enforced boundary with no capability at all,
if unprivileged user namespaces were permitted. Under the deployed posture they are not:

```
unshare(CLONE_NEWUSER) -> -1  errno 1 (EPERM)
```

Blocked by the container runtime's default seccomp/AppArmor profile. Lifting that is itself a
posture change of the same character as a capability grant, so it is not a free route and is not
pursued without the court.

## Conclusion

Option E as the court framed it does not work, on the court's own requested evidence. The reason is
narrow and factual: Codex 0.144.3 keeps sqlite state in CODEX_HOME and will not start without write
access to it. Every repair for that fact runs back into the single shared uid, and every way out of
the single shared uid needs either a capability or a seccomp change.

I record two things honestly rather than treating this as vindication:

- The court was right that I had not tested this, and right that I pled our own
  `validate_cell_layout` rule as though it were the runtime's. That error is corrected in the
  `codex_cell_boundary` docstring under H3, and the submission is withdrawn under H4.
- These findings do not entitle me to re-apply on the old pleading. H6 requires any fresh
  application to plead the COMPLETE grant (including `CAP_CHOWN` or a layout avoiding it), and H7/H8
  require the capability to be cleared from the child's permitted, inheritable and bounding sets
  after the uid change and proved by adversarial test, because setuid between two non-zero uids does
  not clear capabilities and `no-new-privileges` does not make a drop one-way.

Meanwhile the argv and `/etc/codex` pinning is ordered anyway under H5 as free defence in depth, and
`production_ready` stays False under H12.
