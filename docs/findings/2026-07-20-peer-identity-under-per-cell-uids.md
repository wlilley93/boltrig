# Peer-identity attestation is unreadable across per-cell uids (2026-07-20)

## Symptom

A `/v1/spawn` to `codex-worker` on the running dev kernel degrades
`codex_turn_failed:CodexCellStartupError`. The internal cause (now logged) is:

```
PermissionError: [Errno 13] Permission denied: '/proc/<pid>/ns/pid'
  linux_peer_identity.capture_linux_process -> read_link("<pid>/ns/pid")
  codex_trusted_proxy_ingress.capture_cell_identity
  codex_trusted_proxy_provider.register_spawned  (on_spawned, at supervisor.start)
```

## Root cause

`capture_linux_process` reads five things about the freshly spawned cell:
`/proc/<pid>/stat`, `/proc/<pid>/status`, `/proc/<pid>/cgroup` (all world-readable)
and **`readlink /proc/<pid>/ns/pid`** (the pid-namespace inode). Reading an
`ns/*` link requires `PTRACE_MODE_READ_FSCREDS`: same uid as the target, or
`CAP_SYS_PTRACE`.

Under per-cell uids (VJS-CC-VJS 7): the API runs uid 10001 with an empty permitted
set (no `CAP_SYS_PTRACE`), and the cell runs uid 20001. So the API can no longer
readlink the cell's `ns/pid`. This machinery was written for the single-uid model,
where the cell shared the API's uid and the read succeeded. The **verify** side
(`attest_peer_ancestry`, which the ingress uses when the cell's helper connects)
derives the peer's pid-namespace the same way, so it breaks symmetrically.

## Why the field is also redundant now

All cells and the API share the ONE container pid namespace (per-cell uids are not
separate pid namespaces). So `pid_namespace_inode` is identical for the API, every
cell, and the connecting helper: it is a coarse "same container" check, not a
per-cell discriminator. The per-cell discriminator is the **uid**, which is unique
per cell and kernel-attested via `SO_PEERCRED`.

## The fix is J8-directed (not a new fork)

[2026] VJS-CC-VJS 7 **J8** already holds that, because the ingress socket is
abstract and carries no filesystem permission, **peer attestation must require the
peer uid to equal the cell's assigned uid** - i.e. the kernel-attested SO_PEERCRED
uid is the attestation anchor under per-cell uids. So the direction is settled:

- Source the "expected container pid namespace" from a READABLE vantage (the API's
  own `/proc/self/ns/pid`, which is the same shared container ns), not from the
  cell's cross-uid-protected link; OR drop the pid-ns field from the per-cell
  identity and rely on uid (J8) + pid + start_ticks + boot_id + cgroup, which are
  all world-readable.
- Apply the SAME change on the verify side (`attest_peer_ancestry`) so it does not
  read the peer's protected `ns/*` link either.

## Why it needs care, not a tail-end edit

It is a two-sided change (capture + verify) to a security boundary. It MUST land
with an adversarial test proving the property VJS-CC-VJS 5/J9 protect still holds:
a hostile cell A (its own uid) still cannot impersonate cell B at the ingress under
the new identity model. Do it as a focused unit: design the minimal identity set,
change both sides, and add the adversarial ingress test - then re-run the live
`/v1/spawn` proof end to end (expect `output.runtime == "codex_app_server"`, a
`/v1/responses` hop in bifrost logs, and no gateway key in the cell's environ).

## State when this was written

Landed on `main` (b8fe7f0): the provider-wiring gap, the phase-scope gap, and the
per-cell argv fd-path bug are all fixed and deployed; the cell now spawns under its
distinct uid. This `ns/pid` read is the single remaining blocker between "spawns"
and "answers".
