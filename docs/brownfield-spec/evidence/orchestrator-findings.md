# Findings established by the orchestrator, for independent verification

These were derived directly against the pinned tree before and during the
authoring run. They are cross-cutting, so no single area agent owns them. Each
must be independently re-derived before it enters the RISK register.

## F1. Doctrine conformance is asserted in prose and enforced nowhere

- `README.md:67` `"of that doctrine (the K-1..K-30 invariant catalogue)"` names
  `agent-kernel-doctrine` the single source of the K-1..K-30 catalogue, and says
  Boltrig conforms to it.
- Decision `docs/decisions/0002-nankle-consolidation-ruling.md:32` `"Declare
  agent-kernel-doctrine the sole source of K-1..K-30"` makes that a ruling, with
  its evidence listed as prose sections in README and ARCHITECTURE.
- The doctrine's Appendix A defines thirty ids, K-1 through K-30.
- `tests/invariants.yaml` declares 421 invariants and binds exactly SIX K-* ids:
  K-2, K-5, K-9, K-13, K-19, K-20. Twenty-four of the thirty doctrine invariants
  have no bound test here.
- No gate, hook, or CI workflow references the doctrine at all. Bounded search:
  `grep -rn doctrine scripts/*.py scripts/*.sh .github/workflows/*.yml
  .githooks/*` on the pinned tree, 2026-08-24: zero hits.
- The doctrine repository is not pinned to a commit anywhere in this tree. Its
  local checkout was at `9fc8c4e` when this was written, but nothing in Boltrig
  records or checks that.

Consequence: the K-* ids in `tests/invariants.yaml` carry the doctrine's
authority by NAMING it, while their meanings can drift apart silently in either
repository. This is the shape of a citation to another repo's artefact with no
lock on it.

## F2. The invariant catalogue is overwhelmingly local and overwhelmingly security

Prefix census of `tests/invariants.yaml` (bounded: `grep -oE '^  [A-Z][A-Z0-9]*'`
then uniq, pinned tree):

    SEC 230   FR 87   US 26   NFR 15   DIS 10   MEM 8   EMO 7   WRK 6   K 6
    KNO 5   IAC 5   CODEX 5   CONV 3   REL 2   FLT 2   WL 1   P9 1   DH 1   CHAN 1

421 declared invariants, 421 distinct `@pytest.mark.invariant` markers in
`tests/`. The gate's own design is sound: `scripts/check_invariants.py:10`
`"if any declared invariant has zero bound tests"` fails closed on unbound
claims AND on undeclared markers, and its docstring at line 15 states that
`service_gated` bindings report as gated-not-verified so a permanently skipped
test never silently discharges an invariant. That is the correct handling of the
trap and should be said in the corpus as a positive finding, not only as a risk.

## F3. Repository shape

- 1,708 commits, first commit 2026-06-28, referent commit 2026-08-24. The system
  is roughly eight weeks old and carries 154k lines of Python plus 127k lines of
  Python tests plus 100k lines of TypeScript. Test lines are 82 percent of
  source lines.
- Ten open pull requests at the referent, of which seven are Dependabot bumps.
  The two substantive ones are #364 (structural sweep: store pair plus four god
  files under floor) and #362 (providers: one provider's key blocking every
  other, and a doubled /v1).
- Eleven live worktrees on eleven branches existed on this host at capture time
  and are out of scope. Unmerged work is invisible to this corpus.

## F4. Two decision numbers are used twice

`docs/decisions/` contains both `0023-refuse-model-judged-approvals.md` and
`0023-sleep-distillation-and-the-adapter-seam.md`, and both
`0030-agents-tab-built-on-web-sdk.md` and `0030-familiar-modes-and-dials.md`.
A decision id is a citation target. Two documents sharing one id means any
reference to "decision 0023" is ambiguous, and no gate detects it.

## F5. Every composed service carries a restart policy (a negative finding, recorded as such)

All fifteen services in the `services:` block of `docker-compose.yml` (lines 38
to 742 of the pinned file) declare `restart: unless-stopped`: postgres, redis,
kernel, fleet-worker, browser-executor, hatchet-worker, hatchet-engine,
hatchet-dashboard, ui, bifrost, local-model, channel-gateway, signal-cli,
whatsapp-bridge, backup. Bounded: mechanical parse of the top-level service
blocks in that one file on the pinned tree, 2026-08-24. The `.vm.yml` and any
override files were NOT parsed by this check and an override can still remove a
policy, so this finding covers the base compose only.

This is recorded because a service with no restart policy dies at the host's next
reboot and presents later as an unexplained absence. The base compose does not
have that defect.

## F6. The sensitive-to-local residency guarantee has one enforcement point and two write paths (HIGH)

Independently derived by the orchestrator against the pinned tree, after
SPEC-10 raised a narrower version of it. The chain, every link opened and read:

1. The manifest parser accepts `data_class` from YAML with a default and no
   validation at all:
   [`boltrig/config/manifest.py:584`](../../../boltrig/config/manifest.py)
   `"data_class=str(e.get(\"data_class\", \"standard\")),"`.
2. The apply path writes the row straight through:
   [`boltrig/config/manifest_apply.py:177`](../../../boltrig/config/manifest_apply.py)
   `"await store.upsert_model_endpoint(endpoint)"`, inside `_seed_projection`,
   with no data_class or kind check anywhere in the module (bounded: `grep -n
   data_class boltrig/config/manifest_apply.py` returns nothing).
3. The model itself validates only its revision:
   [`boltrig/models/libraries.py:212`](../../../boltrig/models/libraries.py)
   `"def __post_init__(self) -> None:"`, whose only raise is
   `"model endpoint revision must be a positive integer"`.
4. The rule exists in exactly ONE place, on the control-verb path:
   [`boltrig/config/control_model_endpoints.py:178`](../../../boltrig/config/control_model_endpoints.py)
   `"if data_class == \"sensitive\" and kind != \"local\":"`.
   Bounded: `grep -rn sensitive --include=*.py boltrig/ | grep -i 'local\|kind'`
   on the pinned tree finds no other enforcement of the pairing.
5. The router decides sensitive-safety purely on `data_class` and never looks at
   `kind` or at `base_url`:
   [`boltrig/fleet/model_router.py:108`](../../../boltrig/fleet/model_router.py)
   `"if ep is not None and ep.data_class == \"sensitive\":"`, and again for the
   configured fallback at
   [`boltrig/fleet/model_router.py:118`](../../../boltrig/fleet/model_router.py)
   `"if local is not None and local.data_class == \"sensitive\":"`.

So `data_class` is simultaneously the field a manifest sets freely and the only
field the router trusts. `SensitiveDataMisrouted` cannot fire for a row that
claims to be sensitive, whatever its kind or its base_url. AGENTS.md states the
guarantee as absolute: "Sensitive data is gated to local endpoints by the model
router - never weaken that."

**The shipped example proves the two paths disagree.** `manifest.example.yaml`
declares `id: local-sensitive` with `kind: vllm` and `data_class: sensitive`
([`manifest.example.yaml:73`](../../../manifest.example.yaml) `"kind: vllm"`,
[`manifest.example.yaml:76`](../../../manifest.example.yaml)
`"data_class: sensitive"`). The control verb would REFUSE that exact row,
because `vllm` is not `local`. The repository therefore ships a reference
configuration that its own governed authoring path rejects.

That makes this a contradiction, not merely a missing check, and the corrective
is a decision rather than a patch: either `kind == "local"` is the wrong
predicate for localness (it does not admit `vllm` or `ollama` pointed at an
on-box URL, which is what the shipped stack actually runs), or the manifest path
is missing the check. Both cannot be right, and until one is chosen the
guarantee rests on operator discipline rather than on code.

In the SHIPPED configuration no data egresses: `base_url` for that endpoint is
`http://local-model:8000/v1`, the on-box service. The exposure is that nothing
in the code prevents a manifest from pointing a `data_class: sensitive` endpoint
at a remote provider, and the router would use it.

**SETTLED: the invariant that claims to cover this binds only one of the two
authoring paths.** SEC-12's own description states the guarantee as an absolute
that includes authoring:
[`tests/invariants.yaml:757`](../../../tests/invariants.yaml)
`"authoring rejects a sensitive non-local endpoint"`. Its declared binding test
is `tests/security/test_model_endpoint_lifecycle.py::test_endpoint_authoring_enforces_local_sensitive_and_exact_bifrost_ids`,
and that test drives the control verb and nothing else:
[`tests/security/test_model_endpoint_lifecycle.py:450`](../../../tests/security/test_model_endpoint_lifecycle.py)
`"control.model_endpoint.upsert"`. The manifest is also an authoring path and it
is untested here: of the six test files that reference `apply_manifest` or
`_seed_projection`, none mentions `data_class` (bounded: `grep -rln
'apply_manifest\|_seed_projection' tests/` then `grep -l data_class` over that
set, pinned tree, 2026-08-24, zero hits).

So `scripts/check_invariants.py` reports SEC-12 as bound, and the
binding-debt-zero ratchet shows no debt against it, while an entire authoring
path for the exact row the invariant forbids is neither checked nor tested. The
invariant's stated scope is wider than the referent its test binds. That is the
defect, and it is worse than a missing check because the gate actively reports
the claim as discharged.

SEC-31 is unrelated and was a wrong association on first pass: it covers memory
scope isolation
([`tests/invariants.yaml:499`](../../../tests/invariants.yaml)
`"Memory is scope-isolated"`), not model residency.
