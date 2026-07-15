# Boltrig v2 - Path to 10

> Living implementation and release ledger. First written 2026-07-13; refreshed
> 2026-07-15 against the current working tree. The original document was an ambition
> map with point-in-time red counts. Those counts are intentionally not repeated:
> they became stale as the implementation moved. Git history preserves that baseline.

Boltrig remains one in-repo product with four cooperating pieces: the governed
kernel, the store/database, the fleet/runtime, and the browser console. A 10/10 is
not merely a large test count or a polished screen. It is the same behavior proved
locally, enforced in CI, packaged as immutable artifacts, operated through explicit
readiness and recovery contracts, and exercised against the real external services
selected for a deployment.

## 1. Current position

The implementation described below is present in the uncommitted working tree.
The whole-tree `make quality` gate and independent browser acceptance pass are
recorded in section 7. This is a verified local candidate, not a hosted release
attestation: landing, protected CI, signed publication, and credentialed seams remain.

| Axis | Current implementation | What still makes it 10/10 |
|---|---|---|
| Kernel and governance | One dispatch chokepoint, deny-dominant grants, consequence/HITL enforcement, idempotency, bounded audit, and invariant bindings remain the governing model. Compatibility HTTP routes are preserved while mutating authoring/admin operations resolve to governed `control.*` verbs. | Land the tree through review without introducing a second write path. |
| Store and migrations | Alembic is authoritative; `schema.sql` is a tested bootstrap representation. In-memory/Postgres behavior, RLS isolation, migration parity, and restore behavior are gate inputs. | Perform the production restore drill against the chosen off-box target. |
| Reliability and operations | `/healthz` is liveness. `/readyz` is bounded, redacted, and fail-closed over required dependencies, migration head, control-plane/stack-tool posture, and enabled optional services. Secure Compose and production-doctor fixtures are release inputs. | Exercise readiness and recovery in the real deployment, including enabled Hatchet/model-gateway probes and a fresh-database restore. |
| Security and supply chain | Python/JS dependency audit, SAST, IaC scan, full-history secret scan, action linting, container scan, SBOM, digest-pinned release configuration, and signed-image workflow paths are represented in the repo. | Configure required GitHub checks and environment protection; execute signing, attestation, and admission verification in the release environment. |
| Product experience | The logged-in console is a five-zone shell with real Home, Chat, Runs, Build, and Operate surfaces; global command palette and run inspector; responsive navigation; and explicit destructive-action confirmation. | Keep every displayed action backed by a scoped server contract as the product evolves. |
| External integrations | Live seams are isolated behind configuration and opt-in checks rather than faked by the offline suite. | Supply and verify deployment-specific services and credentials listed in section 6. |
| Release discipline | `make quality`, `release-validate`, and `release-up` define local validation, immutable release validation, and no-build startup. The release workflow checks CI/security status for the exact release SHA and produces image/SBOM evidence. | Land the working tree, enable required branch protection, run the hosted workflows, and complete the cutover runbook. |

No historical test, advisory, invariant-debt, structure-violation, or dirty-path count
should be read as current unless it appears in the verification record in section 7.

## 2. Product surface now implemented

The console uses five stable primary zones. Settings is a utility page rather than
a sixth operating zone.

- **Home** is the operational pulse: scoped runtime/component posture, current cost,
  failed or degraded activity, approvals that need attention, budget pressure, recent
  model routing, recent runs, and work in flight. Links lead to the owning surface
  instead of duplicating its controls.
- **Chat** is a persistent work surface with structured streaming, tool/sub-agent
  activity, inline questions and HITL, stop/reconnect behavior, and scoped
  conversations. Structured events remain data; the UI does not flatten them into
  invented prose.
- **Runs** provides a filterable scoped explorer and a global deep-linked run
  inspector. The inspector combines summary, live timeline, execution tree, tool
  calls, approvals when present, and bounded audit context. Unknown and out-of-scope
  run ids share a non-enumerating not-found state.
- **Build** groups Agents, Workflows, Registry, Integrations/Studio, Memory, and
  Evaluations. Capability discovery is caller-scoped. Workflow nodes are drawn only
  from safe control primitives or discovered verbs; unavailable sandbox/code actions
  are not advertised. Studio covers skills, routing/bindings, reviewed adapter
  generation and activation, MCP server registration, and workflow authoring.
- **Operate** groups Work queue, Approvals, Audit & costs, Health, Channels, and
  Admin. The work queue supports project/list/board views, hierarchy, owner/source/
  status/convergence filters, deep links, detail, children, and bounded audit history.
  Approval, clarification, escalation, and question responses use their matching
  governed paths and require an explicit selection plus confirmation. Audit/cost,
  readiness, and administration remain scope-checked by the server.

The shell adds role-gated navigation, a collapsible responsive rail, appearance and
accessibility settings, `Cmd/Ctrl-K` navigation, and stable deep links. Direct URLs
remain compatible; authority is never inferred from whether a link is visible.

## 3. Interface and truthfulness contract

These are release properties, not design suggestions:

1. Existing HTTP compatibility remains unless a route is demonstrably unsafe.
2. Mutating authoring and administration routes call governed `control.*` verbs
   through dispatch. Shared compatibility helpers may adapt response shapes, but may
   not write directly to a store.
3. `/v1/capabilities` is caller-scoped and is the discovery source for nouns, verbs,
   schemas, consequence, bindings, workflow inputs, and agent-capability profiles.
   The console may filter this surface; it must not invent a capability.
4. High-consequence and destructive operations use arm/confirm interaction and the
   server remains authoritative. Approval cards cannot turn an unselected default
   into an accidental approval.
5. Unknown or out-of-scope resources return the same bounded not-found experience;
   the console performs no client-side existence probe that leaks scope.
6. Every new security or reliability guarantee is bound in `tests/invariants.yaml`
   and marked by a passing test before it is called complete.
7. Dev identity controls are visibly development-only. Real authentication and
   authorization are server-side contracts, not UI state.

## 4. One local quality gate

`make quality` is the complete credential-free candidate gate. It composes:

- invariant debt, Ruff, structure ratchets, strict mypy, Postgres-backed pytest, and
  enforced Python coverage;
- pnpm-only lockfile policy, high-advisory audits, UI typecheck/unit coverage/build,
  site strict lint/unit coverage/build, and Chromium Playwright against the real
  in-memory kernel;
- base, secure, release, and secure-release Compose validation;
- a fixture-backed production doctor with no failures;
- Alembic-to-`schema.sql` parity on disposable Postgres;
- hash-enforced Python dependency audit, Bandit, pinned offline Trivy IaC scanning,
  full-history Gitleaks, and pinned actionlint.

CI must run the same target or its exact component targets and aggregate them into a
required status. Splitting jobs for runtime is allowed; weakening or silently
skipping a component is not.

## 5. Release and operations contract

- `make release-validate` rejects incomplete or non-digest image inputs and validates
  the secure, release, backup-enabled Compose model before anything starts.
- `make release-up` pulls those images and starts with `--no-build`; a release host
  must not turn source into an unreviewed image.
- The release workflow is expected to require successful canonical CI and security
  runs for the exact release SHA, scan images, produce CycloneDX SBOMs, sign images
  and attestations, and retain digest evidence.
- `/readyz`, not `/healthz`, is the traffic/readiness decision. It fails closed when
  a required dependency or deployment receipt is missing and probes optional
  Hatchet/model-gateway services when they are enabled.
- Backups are not successful merely because `pg_dump` exited. Scheduled backups must
  be non-empty and verifiable, carry integrity metadata, reach an off-box target, and
  restore into a fresh database during the drill.

Repository implementation of these paths does not prove that hosted branch rules,
release credentials, an image registry, a deployment admission policy, or an off-box
storage account are configured. Those are deployment evidence.

## 6. Explicit external seams

The offline gate must keep these seams fail-safe, but cannot claim them live without
the corresponding environment:

| Seam | In-repo boundary | Evidence required to close it |
|---|---|---|
| Durable execution | Hatchet executor, worker, readiness probe, and live test | Reachable Hatchet engine plus a long/resumed HITL run observed end to end. |
| Real identity | OIDC/PAT verification and claim/grant mapping | Chosen IdP, production issuer/audience/JWKS, login/logout/de-provisioning, and 2FA policy exercised. |
| Models and gateway | Governed model routing, sensitive-route policy, optional gateway readiness | Provider credentials and/or on-box model, live gateway, budget/cost attribution, failover, and sensitive-never-remote proof. |
| Third-party adapters and MCP | Reviewed adapter/MCP registration and governed activation | Reachable service, server-held credential reference, scoped invocation, egress/SSRF checks, and revocation test. |
| External memory projections | Kernel ledger plus configured projection engines | Live Mem0/Cognee/pgvector services selected for deployment, fanout/degradation checks, and erasure verification. |
| Pi runtime and stack tools | Sandboxed sidecar/run-scoped MCP boundary and deployment receipts | Deployed Pi sidecar and stack-owned tools, constrained network/process posture, streaming/degradation checks, and no ambient credential proof. |
| Cloud/edge | Compose/IaC and documented Cloudflare/Azure boundaries | Actual tenant, DNS/TLS, secret store, private networking, monitoring, backup destination, and cutover evidence. |
| Hosted release controls | CI/security/release workflows | Required branch checks, protected environments, registry/signing identity, artifact verification, and a release from the exact reviewed SHA. |

`make live-check` groups opt-in integration legs. A skip caused by absent credentials
is an honest seam result, not offline-gate success and not a product failure.

## 7. Verification record for this snapshot

Update this block only from captured command output after all implementation changes
have stopped.

| Field | Result |
|---|---|
| Candidate branch / SHA | `chokepoint/g2-ai-keys-2026-07-13` / `52820b2` plus the user-owned uncommitted working tree |
| `git diff --check` | PASS |
| `make quality` | PASS on Python 3.14 early-warning leg; CI remains pinned to Python 3.12 |
| Backend/Postgres tests and coverage | 783 passed, 11 skipped; 80.86% line coverage |
| UI unit/coverage/build | 44 files / 211 tests passed; typecheck and production build passed; initial entry 367.73 kB (100.23 kB gzip), below the enforced 400 kB / 110 kB budget |
| Browser Playwright and manual responsive/a11y smoke | 18/18 real-kernel Playwright passed, including six axe surfaces; independent browser pass at desktop, 834x1112, and 390x844 passed with no console warnings/errors |
| Site lint/unit/coverage/build | Strict lint, 11 tests, and Next 16.2.6 production build passed |
| Invariants / structure / mypy | 263 declared/marked, 610 bound tests, debt 0; structure and 51-file strict mypy passed |
| Dependency/SAST/IaC/secret/action scans | Python and pnpm audits, Bandit, pinned Trivy, 439-commit gitleaks, and actionlint passed |
| Compose / doctor / migration parity | Base/secure/release Compose, production-doctor fixture, and 4 migration-parity tests passed |
| `make live-check` pass/skip ledger | 4 passed, 15 credential/environment skips; Hatchet, Cognee, pgvector/RLS, Jira, Graph, and CRM remain explicit live seams |
| Hosted CI/security/release and signed artifacts | `PENDING LANDING AND HOSTED RUN` |

## 8. Remaining path

1. Finish the in-repo implementation and run section 7 from the stable tree.
2. Review and land coherent commits without discarding the user's existing work.
3. Make the canonical quality/security checks required on the protected branch.
4. Publish digest-pinned signed images and verify SBOM/signature/attestation evidence.
5. Configure the selected external services one seam at a time and record their live
   tests; do not block unrelated seams on credentials that have not been supplied.
6. Run secure cutover, fail-closed readiness, backup/restore, rollback, and incident
   drills in the production-shaped environment.
7. Re-baseline this ledger from evidence after every release. Never copy old green or
   red counts forward.
