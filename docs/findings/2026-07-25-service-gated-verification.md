# Service-gated invariants: what now runs, and what each remaining one needs

Date: 2026-07-25

`make invariants` reports some bindings as SERVICE-GATED, meaning declared and
marked but "gated-not-verified offline". That status is honest but it hides a
question worth asking: gated on WHAT, and is it still true? Some had been gated
so long that nobody had checked whether the gate had lifted. This records the
answer for each, so a future reader can tell "needs a credential the Principal
must supply" apart from "nobody has tried recently".

## FR-WFL-17 (live Hatchet fan-out): NOW VERIFIED

Previously unverifiable because Hatchet did not actually work. Durable execution
was silently dead on every stack until 2026-07-25 (see
`2026-07-25-prod-roll-0.3.1.md`): the SDK defaults to TLS while hatchet-lite
serves plaintext gRPC, so the client never connected. With
`HATCHET_CLIENT_TLS_STRATEGY=none` and a minted token, it does.

`test_live_ultracode_run_fans_out_agent_child_tasks`, the binding
`tests/invariants.yaml` names for FR-WFL-17, **passes**. So does
`test_live_invoke_reenters_the_chokepoint`. This invariant has been verified for
the first time.

Run it from the dev box with:

    source <(grep -E '^(HATCHET_CLIENT_TOKEN|HATCHET_CLIENT_TLS_STRATEGY)=' .env)
    export HATCHET_CLIENT_TOKEN HATCHET_CLIENT_TLS_STRATEGY
    export HATCHET_CLIENT_HOST_PORT=127.0.0.1:7077
    BOLTRIG_TEST_DATABASE_URL=<throwaway dsn> DATABASE_URL=<throwaway dsn> \
      .venv/bin/python -m pytest -q tests/integration/test_hatchet_live.py

`HATCHET_CLIENT_HOST_PORT` is the part that is easy to miss and cost the most
time here. The token embeds `grpc_broadcast_address: hatchet-engine:7077`, which
resolves only INSIDE the compose network; from the host the SDK fails with
`DNS server refused query`. The engine is published on the host, so overriding
the host/port makes the suite runnable without joining the network. Allow ~6
minutes; these legs really drive workflow runs.

## Do NOT point the live suite at the dev database (a hypothesis that FAILED)

Recording this because it is a plausible-sounding idea that the evidence refutes,
and the next person will otherwise try it too.

`test_live_workflow_run_pauses_on_gated_step` fails against the throwaway
`boltrig_test` with `checkpoints not ready within 150s: {}` - an empty dict,
meaning no checkpoint was written at all. The obvious inference is that the store
is empty, so the verb the step expects to gate on (`channel.send`, HIGH, which
DOES exist in the dev database) is absent, and the run cannot pause on it.

That inference is wrong, or at least incomplete. Re-run against the seeded dev
database, **all four legs fail** - worse than the two that pass against the
throwaway one. So the empty store is not the cause, and something about running
against the live database actively breaks legs that otherwise pass. A likely
contributor: the dev stack's own `fleet-worker` container is subscribed to the
same Hatchet tenant, so it competes with the worker the test spawns for the same
tasks. That is a hypothesis and it has NOT been verified.

Scoreboard, so the next attempt starts from facts:

| store | result |
| --- | --- |
| throwaway `boltrig_test` | 2 passed, 2 failed |
| seeded dev `boltrig` | 0 passed, 4 failed |

The FR-WFL-17 binding passes in the first configuration, which is what the
invariant needs. The remaining legs want their own investigation.

## FR-WFL-17's siblings: 2 of 4 legs still fail, cause not yet established

`test_live_workflow_run_pauses_on_gated_step` and
`test_live_kill_restart_approve_resume` fail. Both are the most
environment-sensitive legs (HITL pause/resume, and killing and restarting the
worker), and neither has ever run before, so these are not regressions - they are
simply unexamined. They are NOT blocked on a Principal-supplied credential, and
they deserve their own investigation rather than being folded into a gate repair.

## Per-cell-uid gates: NOW VERIFIED

`tests/integration/test_per_cell_uid_gates.py` skips unless `docker` is present
AND `BOLTRIG_PER_CELL_IMAGE` names a built kernel image. Nothing external was
missing; the image just has to be named:

    BOLTRIG_PER_CELL_IMAGE=boltrig/kernel:0.1.0 \
      .venv/bin/python -m pytest -q tests/integration/test_per_cell_uid_gates.py

**3 passed.** These assert the VJS-CC-VJS 7 posture (uid 0 with CAP_SETUID/SETGID
only, dropping to a per-cell uid) against a real container, and they had never
been run.

## FR-OPS-04 (backup/restore drill): NOW VERIFIED

`tests/integration/test_backup_restore.py` skips without
`BOLTRIG_TEST_DATABASE_URL` AND docker. Both are available on the dev box, so it
was never blocked - only unrun. **1 passed**: a real dump restored into a fresh
pinned PostgreSQL container. `docs/PATH-TO-10.md` lists the restore drill as
outstanding release work; it now has evidence.

## MEM-ENG-03 (live Cognee): blocked on a Principal-supplied credential

`tests/integration/test_cognee_engine.py` needs `BOLTRIG_COGNEE_LIVE=1`, the
cognee package, and `LLM_API_KEY` plus the `LLM_PROVIDER` / `LLM_MODEL` /
`LLM_ENDPOINT` and `EMBEDDING_*` set. The API key is the genuine blocker and it
is the Principal's to supply. Named here so it is not mistaken for neglect.

## The broader lesson

The invariant gate's SERVICE-GATED list is not a fixed set of impossibilities.
Three of the four entries examined here turned out to be gated on something
LOCAL and unexamined rather than on anything external:

- FR-WFL-17 was gated on Hatchet, which was quietly broken fleet-wide.
- The per-cell-uid gates only needed an env var naming an image that already existed.
- The backup/restore drill only needed a DSN and docker, both present.

Only MEM-ENG-03 is genuinely credential-blocked. "Service-gated" reads like a
closed question, which is exactly why these sat unexamined; re-test the list
whenever the underlying service changes, and prefer checking to assuming.
