# Per-cell-uid product-path integration gaps (2026-07-20)

Deploying current `main` to the dev box with per-cell uids ON (VJS-CC-VJS 7: container `user:0:0` +
`cap_add [SETUID,SETGID]`, entrypoint forks a uid-0 spawner and drops the API to uid 10001) and then
driving a REAL read-only Codex turn through the product path (`/v1/spawn` -> `codex-worker` ->
provider -> supervisor -> cell_lane -> spawner -> cell -> ingress -> attestation -> model proxy)
surfaced three integration gaps that the J7/J9 gates never exercised. The gates proved the ISOLATION
property (hostile cell A cannot reach cell B's bearer) with a harness that stayed uid 0 and never ran
a real Codex binary through the full provider + ingress + attestation path. "A passing gate proves the
harness, not the product."

## Gap 1 - HOME=/root crashed the API at startup (FIXED)

The container starts as uid 0, so `HOME=/root`. The entrypoint drops the API to uid 10001, but left
`HOME=/root`, which uid 10001 cannot even stat (`/root` is 0700 root). libpq/asyncpg resolves
`~/.postgresql/postgresql.key` during connect-arg parsing and raised `PermissionError`, taking the
whole kernel down before it served a request. The old 0.1.0 image started AS the boltrig user, so
`/root` was never consulted; only the per-cell (uid-0-then-drop) path hits this.

Fix: `scripts/kernel-entrypoint.py` sets `HOME = pwd.getpwuid(API_UID).pw_dir` (`/home/boltrig`, owned
by 10001, world-traversable) right after `drop_privileges`. Kernel now boots healthy, privilege
separation confirmed from `/proc`: PID 1 = uvicorn at uid 10001 with `CapPrm=0` and `NoNewPrivs=1`;
PID 55 = the entrypoint spawner at uid 0 with `CapPrm=...c0` (SETUID+SETGID only).

## Gap 2 - argv[0] fd-exec does not cross the spawner boundary (FIXED)

`PinnedCodexBinary.execution_path` is `/proc/self/fd/<n>` - a fexecve-style path for a TOCTOU-safe
exec on the IN-PROCESS spawn (the forked child inherits the API's fd table). But the spawner is a
SEPARATE process: that fd number is meaningless in it, and the spawner's `parse_spawn_request` pins
`argv[0] == policy.binary.as_posix()`, so it refused the spawn with "spawn argv[0] is not the pinned
binary". Even had it passed, `/proc/self/fd/<n>` in the spawner's child would resolve to the child's
fd table, not the binary.

Fix: `cell_lane._request` sends `argv[0] = binary.path.as_posix()` (the literal pinned path). This is
sound on the spawner path because the binary lives at a fixed, root-owned, world-executable path on a
`read_only` rootfs the cell uid cannot rewrite, so it cannot be swapped between the supervisor's
sha256 verify and the spawner's `execve`. The in-process path still uses `execution_path` (its fd is
valid there). After this fix the cell genuinely execs under its per-cell uid (pid observed at uid
20001).

## Gap 3 - J8 peer-uid attestation reads restricted cross-uid /proc/ns (OPEN, needs design)

`capture_cell_identity` -> `capture_linux_process` reads `/proc/<cell-pid>/ns/pid` to record the
pid-namespace inode. The dropped API (uid 10001, empty permitted set) CANNOT read the `ns/` links of a
uid-20001 cell: `PermissionError: [Errno 13] Permission denied: '/proc/127/ns/pid'`. Everything else
the capture needs (`stat`, `status`, `cgroup`) is world-readable and works cross-uid; only the `ns/`
symlink is restricted to the process owner / CAP_SYS_PTRACE. This is pervasive, not incidental: the
SAME read happens for the connecting helper's ancestry (`model_proxy_peer_ancestry`), and the helper
runs at the cell's uid too, so the whole J8 peer-uid attestation path hits it.

Key fact: the container uses ONE shared pid namespace (the spawner uses `os.fork` with no
`CLONE_NEWPID`), so the pid-namespace inode is a container-wide INVARIANT - identical read from the
API, the spawner, or any cell. So the value is obtainable; only the specific cross-uid read is blocked.

This is a court-conditioned control (VJS-CC-VJS 7 J8: "extend peer attestation to require the peer uid
to equal this cell's assigned uid"), so it is NOT hot-patched here. Two sound designs, to be chosen and
validated against the J9 gate before landing:

1. **Spawner captures identity (preferred, matches the court's model).** The uid-0 spawner reads the
   cell's authoritative `/proc/<pid>/ns/pid` (+ start_ticks) at spawn and returns it in the spawn
   result; the API consumes the spawner-attested identity instead of reading `/proc` itself. This is
   the same "kernel attests, API consumes" shape VJS-CC-VJS 7 already blesses, and it keeps the
   authoritative read where the privilege is.
2. **Shared-namespace invariant.** Read the pid-namespace inode from `/proc/self/ns/pid` (the API's
   own = the container ns = the cell's ns), since it is invariant across the shared namespace. Smaller,
   but changes a security function's semantics for every caller and must be re-argued against a peer in
   a hypothetical different namespace (which the SO_PEERCRED model already assumes away).

Gap 3 was FIXED (2026-07-20, same session): `read_pid_namespace_inode(reader, "self")` sources the
container-invariant inode; `capture_cell_identity` passes it to `capture_linux_process` as
`pid_namespace_inode=`, so the capture completes without the cross-uid read. Sound because the cell is
definitionally in this container's pid namespace. 199 peer-identity/ingress/attestation tests pass.
After the fix the turn advanced past registration into `client.initialize()`.

## Gap 4 - cells cannot traverse the 0700 parent to reach their own slot (FIXED)

`/var/lib/boltrig/codex-cells` was mounted `mode=0700,uid=10001`, but a cell runs at uid 20001+ and
must TRAVERSE that parent to reach its own `slot-N` below. As "other" to owner 10001 under 0700 it had
no access, so the App Server could not read its `CODEX_HOME` ("failed to read CODEX_HOME .../slot-0/...:
Permission denied"). Fix: parent mounted `mode=0711` - grants traverse (`--x`) without list (`r`); a
cell reaches a KNOWN slot path but cannot enumerate the set, and each slot stays `0700` owned by its
own uid so cross-cell access is still refused EACCES. The slot uids are public/deterministic, so
exposing that a sibling path exists leaks nothing. (Confirmed live: codex 0.144.3 runs as uid 20001 and
now writes its slot.)

## Gap 5 - provisioning and the per-cell slot are DISJOINT (CLOSED 2026-07-21)
> **UPDATE 2026-07-21: Gap 5 CLOSED.** Implemented on branch `gap5-percell-provisioning`: spawner `provision` verb (slot-bound, clears a reused slot, creates the tree + config as the cell uid), provider orchestration, validate split, empty-workspace constant, admission slot-shape relaxation, and the connect-time ancestry ns fix. Proven LIVE: a real per-cell Codex turn answered `"A spinlock is a lock that busy-waits in a loop."` (runtime=codex_app_server). `make check` green (1942 passed); J7/J9/J1 adversarial gates all pass.


This is the substantial one. `ProvisioningCodexPhaseAdmissionSource._provision` creates the cell tree
at `cell_root = read_only_cell_root(stack_root, assignment)` = `codex-cells/<cell_id>`, owned by the
API (uid 10001), and mkdirs `home/codex-home/workspace/source` there. But the cell RUNS at uid 2000N
in an assigned per-cell SLOT (`codex-cells/slot-N`, kernel-pre-owned by 2000N), and the supervisor
passes `cwd=layout.workspace` = `cell_root/workspace` (the API-owned tree). So:

- The two halves never meet: the slot's UID is used, but the slot's DIRECTORY is not; the cell's
  actual `home`/`codex_home`/`workspace` are the API-owned `cell_root` the cell (2000N) cannot write.
- Provisioning runs in the API thread (uid 10001), so it cannot create a cell-uid-owned tree anyway -
  and the court REFUSED CAP_CHOWN, so the API cannot chown one either. The ONLY way to get a
  cell-uid-owned tree without chown is the kernel-pre-owned slot tmpfs - which provisioning ignores.

The failure surfaces at admission: `validate_cell_layout` (`codex_cell_policy.py:289`) rejects the
layout, degrading with `codex_turn_failed:CodexCellPolicyError`.

The correct fix is exactly what J2 ordered and is a control-flow reconciliation, not a patch:

1. Allocate the cell's SLOT at (or before) admission, so provisioning knows the slot path + uid.
2. Make `cell_root` BE the assigned slot (`codex-cells/slot-N`), not a by-cell-id API-owned dir.
3. Provision the tree (`home/codex-home/workspace/source`) from a FORKED CHILD that has setuid to the
   cell uid (J2: "provision that tree only from a forked child that has already setuid to the cell
   uid"), writing into the kernel-pre-owned slot.
4. Spawn the cell into the SAME slot; the supervisor's `cwd`/env then point at cell-uid-owned dirs.

This touches court-conditioned J2 and the isolation surface, so it must be built deliberately and
re-validated against the J9 adversarial gate before it lands. It is the natural next beat and the last
thing between the per-cell-uid lane and a live product answer.

## Status of the product turn (honest)

The isolation property (VJS-CC-VJS 7 J9) and the read-only reasoning mechanism (a real 0.144.3 turn
answered "4" via a hand-built graph, per the 2026-07-20 handover) are both already proven. Driving the
turn through the LIVE per-cell-uid product path this session cleared Gaps 1-4 and advanced the turn
from "crashes at startup" to "spawns, execs under its own uid, captures identity, reaches provisioning
validation" - stopping at Gap 5, the disjoint provisioning/slot design. Gaps 1-4 are landed on `main`;
Gap 5 is specified above for its own beat.

## Also fixed this pass: fail-closed-but-silent errors

The trusted-Codex stack fails CLOSED and sanitizes errors at every layer (good for security, blind for
ops). Three swallowed causes were made observable WITHOUT widening what the caller learns:
`CodexRuntime.run` logs the traceback and tags the degrade reason with the exception class;
`CodexCellSupervisor.start` logs the real cause before its sanitized `CodexCellStartupError`; and the
spawner logs the refusal cause before returning the opaque "refused". These turned a black box into a
three-line diagnosis of each gap above.
