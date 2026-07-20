# Handover: the trusted Codex lane, as at 2026-07-20

Author: Lexby. Repo: `~/Projects/boltrig` (branch `main`). Governance: VJS
(`~/Projects/vibe-justice-system`, orders in `.vjs/orders/*.yaml`).

## 0. The goal this all serves

> Make Boltrig's agent runtime be Codex, governed by the kernel, and trustworthy enough that a team
> can rely on it - not just a single hand-built script.

"Trustworthy enough that a team can rely on it" is the load-bearing clause. A single-tenant script
that works is not the goal; the goal is a lane where one tenant's cell cannot reach another's, and
where the kernel's assertions about what the runtime can do are actually true on the wire.

Note on vocabulary, because it has caused confusion once already: **"multiplayer" here means
isolation between concurrent agent cells, not user-facing accounts.** Per-user logins and encrypted
per-user chat are genuinely NOT built and were never in scope for this program.

## 1. Where the lane actually stands

**Working and landed on `main`:**

- Codex 0.144.3 runs as a real App Server cell, spawned and supervised by the kernel.
- Model calls go out through a per-cell loopback proxy which injects a kernel-only upstream key.
  The key is never in the cell's environment; verified absent from `/proc/<pid>/environ`.
- Bearer delivery is Option-B ([2026] VJS-CC-VJS 3): written to the attested socket connection,
  nothing at rest.
- Peer attestation is real SO_PEERCRED / SO_PEERPIDFD ancestry attestation: the registered cell must
  be a strict ancestor of the connecting peer.
- The auth helper is ONE shared, root-owned, mode-0555 program on the read-only image mount,
  argv-parameterised per cell. No per-cell helper file exists any more.
- Stage E is complete: a console chat turn resolves through `RuntimeResolver` ->
  `build_runtime` -> `build_trusted_codex_runtime`, behind `BOLTRIG_CODEX_TRUSTED`, with a
  `codex-worker` in `manifest.yaml`. The provider graph is no longer hand-built by a script.
- The tool ceiling is enforced at the model-proxy chokepoint, on BOTH the request and the response.

**Not true yet, and it matters:** `production_ready` is `False`, and it should stay False. See s.4.

## 2. What was done in this session

### 2.1 The tool ceiling (task #37, then [2026] VJS-CC-VJS 4)

The finding that started it: **Codex 0.144.3 offers its built-in tools on every turn, and
`config.toml` cannot suppress them.** The reviewed `[tools]` table accepts only `web_search` and
`experimental_request_user_input`; `exec_command`, `write_stdin`, `update_plan`,
`request_user_input` and `view_image` are neither suppressible by config nor enumerable by protocol.
So a cell running `approval_policy = "never"` was being handed an unapproved shell inside the kernel
container, and any shell child - being a descendant of the App Server - also satisfies the ancestry
attestation on the bearer ingress.

Admission had asserted for some time that the quarantined lane has no effective tools. That
assertion was simply unenforced on the wire. It is now true, enforced in
`boltrig/fleet/infrastructure/model_proxy_tool_ceiling.py` and applied in
`codex_model_proxy_server.py`, which is the one point every model call must traverse.

**A methodological lesson worth keeping:** the model's own testimony that it "had no shell tool" was
FALSE. Wire capture proved `exec_command` was being offered on every turn. Model testimony about its
own capabilities is not evidence. Capture the wire.

Four limbs were then ordered by the court, and all four are now discharged and merged:

| Limb | What it required | Where it lives |
|---|---|---|
| F3 | the ceiling proved at the chokepoint | `tests/unit/test_model_proxy_tool_ceiling.py` |
| F4(a) | exclusivity: the path cannot escape `/v1` | `codex_model_proxy_server.py` path-escape guard |
| F4(c) | exclusivity: the RESPONSE cannot confer a tool | `ToolCallStreamGuard` |
| F5 | live re-proof on the pinned artifact, as a gate | `tests/integration/test_codex_tool_ceiling_live.py` |
| F6 | fail-closed on any unverifiable body | covered in the server unit tests |
| F7 | record that this is a kernel DETERMINATION | comment above `QUARANTINED_PREFLIGHT_BLOCKERS` |

F5 is worth reading before touching any of it. Two traps were hit building it, and both would make
the test pass while proving nothing:

1. A **mock upstream is not enough.** Codex probes the gateway before the model call and abandons
   the turn on an implausible reply, so no tool set is ever composed and the test observes nothing.
   It must drive the real gateway.
2. A **stand-in helper (`/bin/sh`) makes it vacuous** for the same reason: it cannot deliver a
   bearer, so Codex never makes a model call.

The test therefore captures BOTH sides (recording around `enforce_tool_ceiling`) and asserts the
pinned binary genuinely OFFERED built-ins, so a run where Codex offered nothing fails rather than
passes. It skips loudly unless Linux + the pinned binary + a reachable gateway + the deployed
boundary are all present.

**Proved live in-container**: the pinned binary offered `exec_command`, `update_plan`, `view_image`
in a 28,908-byte request, and none reached upstream. Merged as PR #57 (`4776f08`).

### 2.2 The cross-cell helper-rewrite vector ([2026] VJS-CC-VJS 5)

The court found a vector I had missed and, in doing so, corrected two errors of mine. Both are
recorded because they are the kind of mistake that repeats:

- I pled that this lane was the hardened production path. **It was not**: SO_PEERCRED was wired
  INSIDE the trusted wall.
- I offered "the kernel injects the key server-side" as proof of path exclusivity. It proves
  **credential** exclusivity only, which is a different claim.
- A docstring I had written claiming a rewritten helper "cannot defeat" attestation was circular and
  false; it has been corrected (G7).

The ratio is worth quoting because it generalises well beyond this lane:

> Kernel peer attestation proves the PROVENANCE of a connection, not the INTEGRITY of the program
> that makes it. Where every input to an attestation decision is writable by a party the attestation
> is meant to exclude, the attestation is TRANSITIVELY COMPROMISED and confers no isolation, however
> correct its own logic.

Fixed by moving the helper out of the mutable cell root onto the root-owned read-only image mount,
with a named, runtime-proved boundary (`codex_cell_boundary.py`) re-asserted at ingress startup and
an adversarial cross-cell test (`tests/integration/test_codex_cross_cell_adversarial.py`). This
needed **no new container privileges**.

### 2.3 The ingress socket squat (task #41) - IN FLIGHT, uncommitted

Found by me, not by the court. The ingress socket was a **predictable** filename
(`mp-<sha256(cell_id)[:16]>.sock`) in a tmpfs owned by uid 10001, which is the **same uid the cells
run as**. So a hostile cell could pre-create or replace a sibling's socket file and be handed that
sibling's bearer. Both halves were wrong: the filesystem presence, and the predictability.

Fix: a Linux **abstract-namespace** socket with a **random** token.

- Abstract names have no inode, so there is nothing to create, replace or unlink, and a second
  `bind` of a held name fails `EADDRINUSE` rather than quietly winning a race.
- That alone is insufficient - abstract names live in the network namespace, which the cells share
  with the kernel - so the name is also `secrets.token_hex(16)`, closing the bind race. The name is
  not a secret; it is a race-closer.
- **The critical encoding constraint:** an abstract name begins with a NUL byte, and a NUL can never
  survive `execve` argv. The name reaches the helper through `config.toml` -> the auth `args` array
  -> argv. So it travels as `@boltrig-mp-<32 hex>` (the `ss`/`socat`/systemd convention) and is
  translated to a leading NUL in exactly two places: `PeerAttestationUnixListener.bind` and
  `deploy/codex/model_auth_helper`. The helper REFUSES a value not in `@name` form rather than
  falling back to a path, which would silently reopen the hole.

Files touched (13, all uncommitted at time of writing): the listener, the ingress, the runtime
config request/receipt/TOML/policy trio, the provider, the support layer, the deploy helper, and
five test files. `validate_ingress_socket_path` became `validate_ingress_socket_name` and pins the
exact shape, so a rewritten config naming a filesystem path fails closed. Unit + integration green
(1259 passed, 22 skipped); the full `make check` was running when this was written.

## 3. What is left, in priority order

### 3.1 Land the abstract-socket fix

Gate, branch, PR, merge. Log at `/tmp/abstract-socket-check.log`.

### 3.2 G3: protect `config.toml` (task #40) - REFUSED, and now evidenced

**Status changed since this handover was first written.** The capability application was put to
First Instance and [2026] VJS-CC-VJS 6 (Marchbanks CCJ) **REFUSED** it, with liberty to re-apply.
Read that order before touching G3; it corrects three things I had wrong.

What the order establishes:

- The argv `-c` route wins over `config.toml` for LEAF keys but **table overrides MERGE**, so
  `-c 'mcp_servers={}'` does not remove an attacker-added `[mcp_servers.attacker]`. Same for the
  root-owned `/etc/codex/managed_config.toml`. Verified twice.
- The court's own proposed alternative (one root-owned read-only CODEX_HOME shared by all cells) was
  ordered tested under H1/H2 and **does not work**: Codex 0.144.3 keeps sqlite state inside
  CODEX_HOME and refuses to start without write access. Sticky-bit repairs give nothing under one
  shared uid; unprivileged user namespaces are `EPERM` under the container seccomp. Evidence:
  `docs/findings/2026-07-20-codex-home-writability.md`.
- **`CAP_SETUID` + `CAP_SETGID` was never the minimum sufficient grant.** setuid between two
  non-zero uids does NOT clear capabilities, and `no-new-privileges` does not help
  (`PR_SET_NO_NEW_PRIVS` constrains what `execve` may GRANT, not what a process already holds), so a
  cell could setuid sideways into a sibling. Chowning per-cell trees also needs `CAP_CHOWN`.

Any re-application must satisfy H6 (plead the COMPLETE grant), H7 (clear the capability from the
child's permitted, inheritable and bounding sets before `execve`) and H8 (prove it adversarially).
H5 orders the argv pinning ANYWAY as free defence in depth, which does not discharge G3.

One further note: **argv is not secret.** `auth.args` lands in `/proc/<pid>/cmdline`, readable by
every same-uid cell. Cell ids and socket names are fine there; never migrate a token onto argv.

### 3.3 The `production_ready` flip - COURT, expressly

Do NOT flip it in a commit. [2026] VJS-CC-VJS 4 F9 is explicit:

> Lexby MUST route any future `production_ready` flip to court afresh with directives 3 to 6
> evidenced; this judgment is not that permission.

And VJS-CC-VJS 5 G1 independently bars the flip while any attestation input is writable by another
cell - which G3 leaves open. So G3 gates the flip.

### 3.4 The preflight discharge design - READY, UNAPPLIED

An agent returned full code for discharging four of the seven `QUARANTINED_PREFLIGHT_BLOCKERS`
(`effective_config`, `effective_apps`, `effective_plugins`, `effective_external_agents`). It was
never applied and is the largest piece of ready work sitting idle. `effective_provider` and
`full_generated_schema_contract` are hard-blocked in 0.144.3 and stay. `effective_tools` was
designed as an opt-in limb defaulting OFF.

### 3.5 PR8: the write/effects phase (task #29)

Codex still only reasons. Letting it act is separately court-gated and should not open before the
read-only path has actually been used in anger.

### 3.6 Propagation - NEEDS THE PRINCIPAL

`jellytot-prod` runs `boltrig/kernel:0.1.0` from 2026-07-05 with `BOLTRIG_CODEX_TRUSTED` unset, so
**every fix in this handover is inert there**. Under the standing shipping directive a fix landed in
git but not propagated is not done. Promoting to prod is an outward-facing act and needs Will's
authorization. This is one of only two things genuinely outside the process; the other is the
capability grant in 3.2, if the court orders it.

## 4. Standing traps for whoever picks this up

- **Use `.venv/bin/python`**, not `python` (not on PATH) and not bare `pytest` (broken shebang).
  `python3` works for plain scripts.
- **`make check` exits 137 under load.** That is the OOM killer, not a failure. It happened twice
  this session, both times alongside concurrent docker builds. Re-run serially before diagnosing.
- **The structure gate is real**: 400 lines per file, 80 per function, exemptions in
  `docs/refactoring/structural-exemptions.json`. A refactor got caught at 83/80 this session.
- **`tests/invariants.yaml` drifts** whenever a test is renamed. The gate catches it; expect it.
- **`docker cp` fails into the kernel container** ("rootfs is marked read-only"). Pipe instead:
  `docker exec -i <c> python - < file`.
- **cwd resets between Bash calls.** Prefix with `cd ~/Projects/boltrig`.
- The container's `/var/lib/boltrig/codex-cells` tmpfs is now `noexec`. Keep it that way.

## 5. Governance quick reference

- Check the citator FIRST. A binding ratio on all fours is followed and cited, never re-litigated
  (SPEC-LAW S-11(c)).
- Convene only on the enumerated triggers: first-impression, a genuine distinction, proposing to
  overrule, a Principal instruction conflicting with law, or a discovered breach.
- **Forks go to the court, never to the user.** The phrase is "not my call - the court."
- Only involve the Principal for an external dependency they alone can supply, or authorization for
  an irreversible outward-facing act.

Orders on this lane, all binding:

| Citation | Subject |
|---|---|
| [2026] VJS-CC-VJS 1 | proxy ingress, Option-C attestation-gated issuance |
| [2026] VJS-CC-VJS 2 | sequencing |
| [2026] VJS-CC-VJS 3 | Option-B bearer delivery, nothing at rest |
| [2026] VJS-CC-VJS 4 | `effective_tools`, the four limbs, F9 flip gate |
| [2026] VJS-CC-VJS 5 | per-cell isolation boundary, G1 flip bar, G3 open |
