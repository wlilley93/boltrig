# Hosted Codex production-admission closure

Status: **blocked, fail-closed**. This is a release gate, not a statement that
the core kernel, Worker, or desktop-local agent cannot run. It applies to the
server-side Codex cells that serve browser Chat. The signed Tauri application
uses a separate private local App Server process and local Bash under the
user-selected approval posture; see decision 0027.

## Executable gates

Production admission is closed in two independent places:

- `CodexAgentRuntime.production_ready` is `False` in
  `boltrig/fleet/infrastructure/codex_agent_runtime.py`. Its constructor also
  requires `allow_test_only_runtime=True`.
- `CODEX_RUNTIME_CONFIG_PRODUCTION_READY` is `False` in
  `boltrig/fleet/infrastructure/codex_runtime_config.py`. A config receipt is
  invalid if it claims otherwise.

Those constants are not the only executable controls:

- `CodexAgentRuntime` refuses construction unless
  `allow_test_only_runtime=True`, and `build_trusted_codex_runtime` always uses
  that test-only constructor path.
- `boltrig/fleet/codex_trusted_wall.py` rejects every production or staging
  signal before runtime construction.
- `CodexRuntimeConfigReceipt` accepts only `production_ready=False`, while
  non-empty `surface_attestations` are rejected because no governed verifier
  exists yet.
- `QuarantinedCodexPreflightReceipt.production_complete` is always `False` and
  requires the complete fixed blocker tuple below.

Neither an environment variable nor a successful local probe can override
these controls. Opening only the two constants also remains red in the shared
release projection while the only receipt is quarantined.

The shared redacted projection is
`boltrig/observability/codex_admission.py::codex_release_posture`. A requested
Codex runtime now appears as:

- `codex_runtime: failed / production_gate_closed` in production `/readyz`;
- a deploy-blocking `codex_runtime` failure in `boltrig doctor --production`;
- `test_only / production_gate_closed` in development readiness.

This prevents a healthy database, Redis and HTTP server from being mistaken for
a production-ready agent runtime.

## Evidence still missing

The only implemented pre-thread evidence type is
`QuarantinedCodexPreflightReceipt`. It is permanently incomplete and records
these seven blockers:

1. `effective_apps`
2. `effective_config`
3. `effective_external_agents`
4. `effective_plugins`
5. `effective_provider`
6. `effective_tools`
7. `full_generated_schema_contract`

| Blocker | Evidence the production receipt must bind | Present local limit |
|---|---|---|
| `effective_config` | Strict `config/read` response, including layers, canonicalised and compared with the exact composed cell config | Implemented in the quarantined pre-thread receipt and exercised against both reviewed Linux artifacts; it remains quarantined until a complete production receipt can bind every limb |
| `effective_apps` | Complete, pagination-safe `app/list` inventory with an exact-schema digest and the expected empty/allowed set | Implemented as forced-refresh, bounded, empty-only evidence in the quarantined receipt |
| `effective_plugins` | Complete, pagination-safe `plugin/list` inventory with an exact-schema digest and the expected empty set | Implemented as local-marketplace, exact-shape, empty-only evidence in the quarantined receipt |
| `effective_external_agents` | Read-only `externalAgentConfig/detect` over the governed home/workspace roots, with every returned migration surface rejected or digested under policy | Implemented over the exact cell workspace plus governed home discovery; any returned item fails closed |
| `effective_tools` | The kernel's per-cell model-proxy ceiling, bound to assignment/model/policy and re-proved on both sides of the live wire | The exact sorted ceiling is now bound into the admitted-cell evidence and checked against the admission; the credentialed live wire re-proof still needs the release Linux boundary and gateway |
| `effective_provider` | Pre-thread runtime evidence naming the effective provider and contract for the exact cell/model, not the provider Boltrig intended to configure | 0.144.3 has no sufficient pre-thread method; `model/list`, `config/read` and post-start thread fields do not prove this limb |
| `full_generated_schema_contract` | Runtime evidence for the complete stable surface, tied to the exact binary and the checked-in full generated bundle | The offline binary/bundle digest gate is supply-chain evidence, but 0.144.3 cannot self-attest the complete effective schema surface required by the admission ruling |

The locally observable limbs are now implemented and adversarially tested in an
immutable, cell-bound *quarantined* receipt. The receipt digests the complete
validated responses and the exact model-proxy tool ceiling. It intentionally
keeps all seven production blockers: partial evidence cannot be promoted into a
production attestation while the provider and complete running-schema limbs are
unavailable.

The pinned protocol does not provide a complete effective-provider inventory or
a complete self-description of every generated schema surface. Those two limbs
cannot be inferred from the config Boltrig intended to write: intended config is
not evidence of the runtime's effective state. They require a newly evaluated,
exactly pinned Codex release that exposes sufficient evidence, followed by a
new checked-in schema bundle and binary digest.

## Codex 0.145.0 candidate screen: no-go

The installed 0.145.0 release was screened on 2026-08-12 without authentication
or a model call. The official x86-64 Linux npm artifact was also generated in an
isolated Linux container, so this conclusion does not rely on the macOS build.
These values are observations, **not** a new fleet pin or production authority:

- candidate: `@openai/codex@0.145.0-linux-x64`;
- Linux binary SHA-256:
  `a2a05dafaa1acb002a45eaec0a462de5b13694fcfcd7bc43305f14781ce7be14`;
- generated files: 273 (the 0.144.3 pin records 267);
- canonical stable-v2 root SHA-256:
  `8930e344c5966ee40efd550001841dd9dfccc71562c3e2b985266e015ab1201b`;
- canonical full-bundle SHA-256:
  `78ba024c8fa1ac1446fe280f3004a07ee075bc867a4567df2d22265fcfa22c2a`.

The macOS arm64 and Linux x64 generators produced the same canonical root and
full-bundle digests. Relative to 0.144.3, the complete method-token set grew
from 155 to 159. The only additions were `app/installed`, `app/read`,
`thread/environment/connected` and `thread/environment/disconnected`.

That is useful future evidence for `effective_apps`, but it does not discharge
either hard blocker:

- `modelProvider/capabilities/read` still accepts an empty object and returns
  only the three booleans `imageGeneration`, `namespaceTools` and `webSearch`.
  `model/list` entries have no provider field. `config/read` can return the
  configured `model_provider`, but the official contract defines it as the
  effective configuration on disk, not proof of the provider implementation
  the runtime resolved. `thread/start` returns `modelProvider`, but that is
  post-preflight and cannot satisfy a pre-thread admission condition.
- No request reports a protocol/schema version, root digest or full-bundle
  digest. `initialize.userAgent` remains an unconstrained string. The CLI can
  generate a version-specific schema bundle, but 0.144.3 already had that
  offline capability; 0.145.0 adds no runtime evidence binding the executing
  cell to the complete generated contract.

The [official App Server documentation](https://developers.openai.com/codex/app-server)
confirms that generated artifacts are specific to the CLI version and describes
`modelProvider/capabilities/read` as capability bounds. The
[official 0.145.0 changelog](https://developers.openai.com/codex/changelog)
records history/import, Bedrock, audio and multi-agent work, but no provider- or
schema-identity RPC. Upgrade verdict: **do not move the Boltrig pin to 0.145.0
for production admission**. It creates protocol churn while leaving both hard
blockers intact.

For the next candidate, reject it at the schema pre-screen unless a stable,
pre-thread response binds (1) the effective provider id and provider contract
and (2) the running protocol/schema identity, including a complete-bundle
digest or equivalently strong canonical identity. Only then is a Linux binary
pin, full receipt implementation and live acceptance run worth starting.

## Authority and external evidence

The final flip is not ordinary implementation discretion. The standing record
at `[2026] VJS-CC-VJS 4 F9` requires a fresh production-ready application with
the ordered evidence; `[2026] VJS-CC-VJS 5 G1` also bars relying on an
attestation input writable by another cell. The per-cell-uid work addresses the
second condition, but it does not supply the missing protocol evidence or the
fresh authority. Code and a local test report cannot create that authority.

After the local receipt work, the remaining non-local evidence is exact:

- a candidate Codex binary whose stable protocol supplies the two missing
  effective-state limbs, plus its generated bundle and reviewed digest;
- the release Linux image with per-cell UIDs, peer credentials, AppArmor and
  the shared helper installed, for the pinned live/adversarial gates;
- a reachable Bifrost/provider staging route and non-production credentials for
  the non-effectful canary (this may incur model usage);
- real camera/UVC hardware only for device capture acceptance, not for Codex
  admission; and
- the fresh authority record after all preceding evidence is attached.

## Closure sequence

Do these in order. Do not flip either production constant early.

1. Select a Codex release whose stable App Server API can report every remaining
   effective surface, especially provider and complete schema identity.
2. Vendor its full generated schema bundle, pin the target and binary digest,
   and extend `scripts/check_codex_protocol.py` so drift is fatal.
3. Replace the quarantined receipt on the production path with a distinct,
   immutable production-preflight receipt. Bind it to the exact binary, schema
   bundle, cell/process identity, assignment, workspace projection, model and
   policy/config digests. Persist signed, fresh evidence; never accept a caller
   assertion.
4. Prove all seven limbs fail closed under omitted, additional, reordered,
   malformed, stale and cross-cell evidence. Re-run the live proxy tool-ceiling
   and pinned-cell probes against that exact binary.
5. Run the per-cell UID, peer-credential, sandbox engagement and adversarial
   two-cell suites on the release Linux image. A macOS unit pass is not a
   substitute.
6. Submit the complete evidence for the fresh production-ready authority
   required by the standing decisions. Record the authority with the release;
   code cannot mint it.
7. Only in the authority-backed change, open both constants, remove the
   test-only constructor requirement from the production composition, and
   update the trusted wall. The same change must keep `/readyz` and production
   doctor red unless the live, fresh evidence is present.
8. Run a credentialed, non-effectful staging canary, then the cancellation,
   bearer-revocation, reconnect, rollback and observation-window exercises
   before routing production work.

## What can ship before closure

- A local single-operator development release is viable now with
  `BOLTRIG_DEV_AUTH=1`, no real ingress posture and no production/staging signal.
- The kernel, Worker and other non-Codex services can be deployed with Codex
  disabled, provided the release is described as core/service staging rather
  than agent-runtime acceptance.
- A real staging deployment whose purpose is to accept Codex-backed agent work
  is **not** viable: `staging` is deliberately a production signal and the wall
  refuses it. Running staging without that signal would merely rename the dev
  posture and is not acceptance evidence.

Provider credentials, a pinned Linux image and live hardware/services are needed
only after the local contract work above. No paid model call is required to keep
the gate closed or to implement the missing receipt contract.
