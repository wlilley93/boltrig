# Risks harvested from SPEC-13-api-composition-bootstrap.md

RISK: `boltrig audit-verify` exists, is tested, and is scheduled by NOTHING. Its
own docstring says it exists so a cron can re-derive the chain
([`boltrig/api/audit_verify.py:1`](../../../boltrig/api/audit_verify.py)
`"from a shell, so a cron or a"`), yet no compose service, healthcheck,
Makefile target, deploy unit or genesis phase invokes it (bounded:
`grep -rn "audit-verify" .` over the pinned tree excluding
`docs/brownfield-spec/`, 2026-08-24). This is the same "a ledger nobody
re-derives" shape the file was written to close, one level up.

---

RISK: The API's chat factory RE-READS the manifest from disk at lifespan time,
which is a second manifest load in a process the composition invariant says
loads at most one snapshot
([`boltrig/api/bootstrap.py:590`](../../../boltrig/api/bootstrap.py)
`"chat_cfg = load_manifest(manifest_path).chat"`). The Hatchet path takes the
same value off the snapshot instead
([`boltrig/fleet/hatchet_bootstrap.py:92`](../../../boltrig/fleet/hatchet_bootstrap.py)
`"chat_config=manifest.chat if manifest is not None else None,"`), so the two
processes can disagree about `chat` if the file changes between the API's import
and its lifespan.

---

RISK: That same re-read swallows every exception into `pass`, so a manifest that
became unreadable after import silently downgrades chat to the default
`ChatConfig()` rather than failing
([`boltrig/api/bootstrap.py:591`](../../../boltrig/api/bootstrap.py)
`"except Exception:"`, and the default at
[`boltrig/fleet/chat.py:91`](../../../boltrig/fleet/chat.py)
`"self._cfg = chat_config if chat_config is not None else ChatConfig()"`).

---

RISK: The `pump` leg of the HITL answer bridge is never wired in the process
that ANSWERS. The API passes `executor` and `resume_held_write` but no pump
([`boltrig/api/platform_bootstrap.py:108`](../../../boltrig/api/platform_bootstrap.py)
`"wire_hitl_resume(kernel, executor=executor, resume_held_write=resume_held_write)"`),
so `pump.requeue` fires only in the Hatchet worker's own kernel, whose notifier
is reached only when that process itself answers a request. A parked
AWAITING_HUMAN work item answered through the API is therefore requeued by no
leg of the bridge.

---

RISK: `boltrig smoke` and `boltrig check-invariants` are inert in both shipped
images. `_repo_script` looks for `<package parent>/scripts/<name>`
([`boltrig/api/cli.py:27`](../../../boltrig/api/cli.py)
`"path = os.path.join(here, \"scripts\", name)"`) and neither Dockerfile copies
`scripts/` (bounded: `grep -n "^COPY\|^ADD" deploy/*.Dockerfile`, 2026-08-24).
Both commands are advertised in the module docstring and in `--help` without a
note that they only work from a checkout.

---

RISK: Only two of the four shipped python entrypoints configure logging.
`boltrig/fleet/hatchet_worker.py` and `boltrig/fleet/browser_executor` call
neither `configure_logging()` nor `basicConfig` (bounded:
`grep -rn "configure_logging\|basicConfig" boltrig/ services/ scripts/*.py`,
2026-08-24, pinned tree; the only hits are `asgi.py`, `worker.py` and
`logging_config.py` itself). The gate that enforces the rule checks exactly two
filenames ([`tests/unit/test_logging_is_configured.py:94`](../../../tests/unit/test_logging_is_configured.py)
`"for name in (\"asgi.py\", \"worker.py\"):"`), so the two newer processes
reproduce the handler-less root the module exists to end.

---

RISK: `boltrig initiate`'s run-once guard is a read-then-write with no
transaction and no uniqueness constraint on "at most one owner-tier user per
tenant", so two concurrent runs with DIFFERENT emails both seat a superadmin.
The module documents this honestly and accepts it
([`boltrig/api/initiate.py:13`](../../../boltrig/api/initiate.py)
`"KNOWN LIMIT - the \"refusing to run twice\" guard is a read-then-write."`).
The sequential refusal IS tested, "which is precisely what makes the race look
covered" (:20).

---

RISK: `boltrig initiate`, `set-password` and `mint-token` are bound to NO
invariant id. These three are the host-boundary commands, the ones that can act
as somebody else, and the host-boundary attribution rule they exist to satisfy
has tests but no `@pytest.mark.invariant` marker (bounded: `grep -n "invariant"
tests/security/test_operator_seat_ratchet.py tests/security/test_set_password.py`
returns nothing, and `grep -n "initiate\|set-password\|host-boundary"
tests/invariants.yaml` returns no matching entry, 2026-08-24). AGENTS.md
requires exactly this pinning
([`AGENTS.md:53`](../../../AGENTS.md) `"Every security or correctness claim must be pinned to a test with"`).

---

RISK: The audit-key guard fails OPEN when nothing sets a production signal, and
nothing in the shipped compose sets one. The code says so in its own comment:
[`boltrig/api/boot_guards.py:67`](../../../boltrig/api/boot_guards.py)
`"Nothing sets a production signal by default"`.
A deployment that follows the documented `cp .env.example .env` will warn once
per boot and then run a hash chain keyed by a public constant.

---

RISK: `bootstrap.build_kernel()` is DEAD. Its docstring claims it is the
"Synchronous entrypoint for uvicorn/worker import-time construction"
([`boltrig/api/bootstrap.py:472`](../../../boltrig/api/bootstrap.py)
`"def build_kernel() -> Kernel:"`), but uvicorn reaches `build_app` and the
worker reaches `build_kernel_async`. Bounded: `rg -n "build_kernel\b" .`
over the pinned tree, 2026-08-24; every hit is either `build_kernel_async` or
`tests/conftest.py::_build_kernel`, a different symbol. A prose claim naming two
callers that do not exist is a live drift hazard.

---

RISK: `BOLTRIG_EMOTION` is compared with a strict `== "1"`
([`boltrig/api/bootstrap.py:289`](../../../boltrig/api/bootstrap.py)
`"BOLTRIG_EMOTION\", \"\").strip() == \"1\""`), while every other flag in this
file goes through `is_truthy`. `BOLTRIG_EMOTION=true` silently registers nothing
on the manifest path.

---

RISK: A wrong `BOLTRIG_MANIFEST` path is silently ignored rather than refused.
`_find` returns the first path that EXISTS and the env value is simply the first
candidate ([`boltrig/api/bootstrap.py:67`](../../../boltrig/api/bootstrap.py)
`"def _find(paths) -> str | None:"`), so a typo boots the repository's
`manifest.example.yaml` and logs it as a normal manifest boot.

---

RISK: `boltrig audit-verify --tenant` defaults to `BOLTRIG_TENANT_ID` or
`default` ([`boltrig/api/audit_verify.py:103`](../../../boltrig/api/audit_verify.py)
`"default=os.environ.get(\"BOLTRIG_TENANT_ID\", \"default\")"`), which is not
necessarily the manifest's tenant. Verifying the wrong tenant's empty chain
exits 0, and nothing in the command compares the tenant against the manifest.

---

RISK: `docs/decisions/0018-held-write-resume.md` is stale on a load-bearing
fact. Its reserved section asserts nothing serves the Hatchet tasks
([`docs/decisions/0018-held-write-resume.md:325`](../../../docs/decisions/0018-held-write-resume.md)
`"stack serves the Hatchet tasks"`), which the
`hatchet-worker` compose service now contradicts. A reader who trusts the
decision would conclude the durable lane is dead when it is served.
