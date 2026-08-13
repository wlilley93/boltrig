# 2026-07-27: retiring the Pi lane, and two things found on the way

The Pi retirement itself is recorded in `docs/decisions/0020-retire-the-pi-lane.md`.
This is the operational record: what was actually true on the boxes, where my own
plan was wrong, and two defects that have nothing to do with Pi and were found only
because the retirement went looking.

## What the fleet actually looked like

Both stacks on the production host, before any change:

| fact | app.boltrig.io | Classical Visas |
| --- | --- | --- |
| `BOLTRIG_ENABLE_LEGACY_RUNTIMES` | unset | unset |
| `pi-sidecar` container | `Up 8 days (healthy)` | (shared, one container) |
| real `POST /run`, 6-27 July | 1, on 2026-07-06 | - |
| health probes, same window | 61,212 | - |
| `PI_SIDECAR_TOKEN` in container env | set | set, different value |
| `manifest.yaml` `runtimes.pi.enabled` | absent | **true**, pointing at `http://pi-sidecar:8090` |

## Where my plan was wrong, twice, in the same direction

The plan said the deployed base compose would resurrect the sidecar on the next
`compose up -d`. **It would not, for two independent reasons**, and I found the
second only by measuring the thing rather than the file:

1. The service carries `profiles: ["legacy"]`, so `up -d` never starts it without
   the profile, and no tenant script passes one. The container had been started by
   hand at some point, and `restart: unless-stopped` kept it alive afterwards.
2. `docker compose config` **excludes profiled services by default**, so
   `pi-sidecar` was never in either stack's resolved model at all. The proof is the
   before/after diff of both resolved configs across the compose change: **empty**.
   Removing 46 lines from the base manifest changed neither tenant's model, because
   neither tenant's model had ever contained them.

Both errors pointed the same way: I overstated an urgency. The removal was still
worth making durable, but the sentence "the next `up -d` brings it back" was not
true when I wrote it, and the record should say so rather than quietly carry it.

## What the real residue was

Not the service. The **credentials and dead configuration injected into live
containers**. Every name in this paragraph was deleted by this change and is read by
nothing now: `PI_SIDECAR_TOKEN` (a real bearer, different per tenant) was removed,
`BOLTRIG_PI_SIDECAR_URL` was removed, `BOLTRIG_PI_MCP_URL` was removed,
`BOLTRIG_PI_MAX_STEPS` was removed, `PI_SIDECAR_EGRESS_ALLOW` was removed, and
`pi-sidecar` was taken out of CV's `NO_PROXY` bypass list. All of it was still being
handed to every kernel and fleet-worker on both stacks after the container was gone.

Removed from `~/Projects/boltrig-main/.env` and
`~/Projects/opbox-prod/boltrig-tenants/cv/boltrig.env` (both backed up), and CV's
`manifest.yaml` lost its `runtimes.pi` block. Verified afterwards by reading `env`
**inside all four running containers**: zero Pi variables, on both tenants.

Both stacks re-converged and healthy, `app.boltrig.io` and `boltrig.io` 200,
`/readyz` `ready` on both kernels, no `pi-sidecar` container in `docker ps -a`.

Note the new `retired_runtime_pi` doctor check does NOT run on these boxes yet: they
are on kernel 0.4.11, which predates it. It ships with the next release, and by then
the drift it reports is already closed.

---

## Side finding 1: a merged fix had been stranded for three days

`~/Projects/boltrig-main` is a checkout of `main` and it was **57 commits behind**.
The `app.boltrig.io` stack bind-mounts `libraries/` from that tree straight into the
running kernel and fleet-worker, so the live app was serving a three-day-old skills
library.

Among those 57 commits was the fix for this, in `libraries/skills/ops/opbox.yaml`:

> The previous enumeration named eight verbs in the opbox KERNEL door's noun-first
> form (`opbox.matter.list`); the tenant runs the FRONTEND door's verb-first form
> (`opbox.list_matters`), so ZERO of them resolved and this skill's opbox reach was
> nil from 2026-07-24 until 2026-07-27.

The fix was written, tested, merged, and reached no tenant. The capability stayed
dead on the live box for three days. Pulling the tree for the Pi retirement is what
delivered it, which is luck, not process.

**This is the standing rule failing in its own terms**: a fix is not done until it
reaches every deployment that runs it. A bind-mounted directory is a deployment
surface exactly like an image tag, and nothing was watching this one. `git pull` on
that tree is a deploy step for `app.boltrig.io`, and it is not in any runbook.

## Side finding 2: two Codex app-server tests fail only in the full suite

`test_codex_runtime_preflight_hardening.py::test_skills_reject_unexpected_security_
relevant_fields_at_every_level[skill-item]` and
`test_codex_app_server_adversarial.py::test_first_late_timeout_response_is_discarded_
but_duplicate_fails` each failed once across five full `make python-quality` runs
today, and neither reproduces in isolation or under moderate parallel load.

**It is a test-design defect, not a product one, and the distinction matters.** The
cause is visible in the fixtures:

```
tests/unit/codex_app_server_fakes.py:108        request_timeout: float = 0.2
tests/unit/test_codex_app_server_adversarial.py:84    request_timeout=0.015
tests/unit/test_codex_app_server_adversarial.py:140   request_timeout=0.01
tests/unit/test_codex_app_server_adversarial.py:238   request_timeout=0.015
```

A **15 millisecond** wall-clock budget, on a test that then does several `await`
hops on an event loop shared with 2,749 other tests. The adversarial case creates a
`live_task` it expects to SUCCEED, and under a loaded loop that request's own 15ms
expires before its response is delivered, so the live request times out too. The
first failure has the same shape one layer up: `_wait_for_response` raised
`TimeoutError` on a future the traceback shows as **already finished**, because the
deadline was exhausted before the `await` began.

The product's timeout behaviour is correct in both. What is wrong is a test that
asserts a request will NOT time out while giving it a budget shorter than a GC pause.

Not fixed here: it is unrelated to the retirement and belongs in its own change. The
shape of the fix is that a test wanting a timeout should get it by never delivering
a response, not by making the budget too small for the machine, so the tiny value
can be reserved for the request that is meant to expire.

**It matters because a green suite is the thing every gate here rests on.** A
1-in-5 failure that only appears at full scale is indistinguishable, on the day it
happens, from a real regression in the runtime the whole product now depends on.
