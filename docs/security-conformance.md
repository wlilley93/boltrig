# Security conformance ledger (Batch 1 + Batch 2)

The honest implemented-vs-scaffolded map for the two security-hardening specs
(`requirements-security-batch1.md`, `requirements-security-batch2.md`). Per
`AGENTS.md`: never describe a seam as wired. Status per control family:

- **BUILT** - enforced in code and pinned to a `SEC-*`/`FR-*` invariant (binding
  debt 0).
- **HARDENED (this round)** - a real gap closed in the security-hardening round
  and bound (the SEC-58..63 set).
- **SEAM** - real interface / documented, but needs an environment, an external
  service, or ops config the engine cannot exercise here (Principal-owned).

## Batch 1 (zero-trust) - by family

| Family | Status | Notes / invariants |
| --- | --- | --- |
| **IAM** (identity/auth) | **MOSTLY BUILT + HARDENED** | IAM-01/10 verified-claims + fail-closed (SEC-01); IAM-16 delegation intersection, IAM-15 run-scoped MCP tokens (SEC-27). HARDENED this round: IAM-02 alg allowlist, IAM-03 exp-required + lifetime cap + leeway<=120s, IAM-04 access-token-only, IAM-05 JWKS TTL + kid-miss refetch + timeout (SEC-59); IAM-09 dev-auth refuses prod (SEC-60). SEAM: IAM-08 SAML, IAM-11 MFA (IdP-delegated), IAM-14 mTLS service-to-service (deploy). |
| **AZ** (authz/tenancy) | **MOSTLY BUILT + HARDENED** | AZ-02 deny-dominant/fail-closed grants (SEC-07/08), AZ-08 HITL step-up (SEC-14), AZ-09 no-test-escalation (SEC-29), AZ-10 budget-reservation (built). AZ-02 wildcard-boundary HARDENED with id normalization (SEC-62). PARTIAL/SEAM: AZ-04 Postgres RLS (schema/role - deploy), AZ-03 BOLA is per-route (kernel verbs are tenant-scoped; a full per-route audit is a follow-on). |
| **AGT** (agent/LLM/MCP) | **BUILT** | AGT-04 depth/budget caps, AGT-05 least-privilege ephemerals, AGT-06 sandboxed sidecar (SEC-24/27), AGT-09 MCP chokepoint parity (SEC-26), AGT-11 sensitive->local (SEC-12), AGT-12 no-secrets-in-prompt. AGT-07 sidecar egress is enforced in the manifest (SEC-48). |
| **INJ** (injection) | **BUILT + HARDENED** | INJ-01 parameterised SQL (sql_base), INJ-05 no insecure deserialization (none present), INJ-06 schema validation (SEC-21). HARDENED: INJ-02 shared egress/SSRF guard incl. metadata block applied to all HTTP adapters (SEC-61). SEAM: INJ-03 full script-runtime sandbox (the script runtime is a seam). |
| **WEB** (site) | **HARDENED (this round)** | WEB-02/03 security headers, WEB-05 CORS allowlist, WEB-06 Host validation now installed on the kernel app (SEC-58). UI-side WEB-01/08 live in the frontend. SEAM: WEB-07 authenticated origin-checked streaming hardening beyond current SSE auth. |
| **KEY** (secrets) | **BUILT + SEAM** | KEY-02 references-only at rest (built), KEY-03 secrets never in audit/agent/client (SEC-05). SEAM: KEY-01 external secret manager (Vault/KMS - deploy), KEY-05/07/08 rotation/scanning/no-defaults (ops/CI). |
| **DATA** (privacy) | **BUILT + SEAM** | DATA-04 PII redaction + sensitive->local (SEC-12), DATA-05 tamper-evident hash-chained audit (SEC-19/20), DATA-03 tenant isolation (SEC-09), DATA-07 retention/erasure (built). SEAM: DATA-01/02 TLS-everywhere + encryption-at-rest (deploy overlay), DATA-06 tested restore (ops). |
| **ADP** (adapters) | **BUILT + HARDENED** | ADP-02 credential confinement (SEC-05), ADP-04 generated-adapter review gate (SEC-22), ADP-10 high-consequence marking (SEC-39), ADP-09 MCP-consumer isolation. HARDENED: ADP-03 per-adapter metadata egress block (SEC-61), ADP-08 webhook replay window (SEC-63). |
| **SUP** (supply chain) | **SEAM** | SUP-01/02/03/04 pinned+hash-locked deps, SCA, SBOM, signing; SUP-06 the CI gate must run - **GitHub Actions is billing-blocked (Principal action)**. All CI/ops. |
| **INF** (infra) | **SEAM** | INF-01 hardened containers (Dockerfile non-root/read-only/caps), INF-03 network segmentation, INF-05 least-priv DB role - deploy/ops. Partially expressible in the compose/Dockerfiles (a follow-on); not exercised here. |
| **DET** (detection) | **PARTIAL + SEAM** | DET-01 security-event logging via the audit log (built); DET-03/04/05 anomaly alerting, IR playbooks, periodic pen-test - ops/SIEM (seam). |

## Batch 2 (Azure/cloud/host/runtime) - by family

| Family | Status | Notes |
| --- | --- | --- |
| **PI** (runtime) | **BUILT (the kernel-side controls) + SEAM** | PI-04 authenticated internal control channel + PI-08 model-key/provider pinning + PI-05 step caps (SEC-24/27, the sidecar). PI-01/02/03 (disable native tools/self-extension, micro-VM isolation) become real when the real Pi loop replaces the stand-in (the documented seam); PI-07 telemetry-off is a deploy/runtime setting. |
| **CLOUD** (Azure) | **SEAM + HARDENED (the one code part)** | CLOUD-03 IMDS blocked from agent egress paths is HARDENED in code (SEC-61). Everything else (managed identity, Key Vault, private endpoints, NSG/firewall, WAF, Defender) is Azure config - Principal/ops seam. |
| **HOST** (Linux/container) | **SEAM** | CIS baseline, rootless/user-ns, bastion SSH, auditd - host/ops. |
| **CRYPTO** | **BUILT + HARDENED** | CRYPTO-01 approved hash (SHA-256 audit chain), CRYPTO-02 CSPRNG for all tokens/ids (built). HARDENED: CRYPTO-04 constant-time PAT compare (matches the webhook path). SEAM: CRYPTO-03 TLS policy (edge/deploy), CRYPTO-05 KMS key lifecycle. |
| **RES** (DoS/resource) | **PARTIAL + HARDENED** | RES-01 request-body cap HARDENED (SEC-58); rate limiting + budgets built (AGT-04). SEAM: RES-02 stream caps, RES-05 per-tenant quotas, RES-04 queue backpressure (infra). |
| **UPLOAD** (ingestion) | **PARTIAL + HARDENED** | UPLOAD-05 identifier normalization HARDENED (SEC-62); UPLOAD-02 spec-fetch SSRF reuses the egress guard (SEC-61); ADP-04 generated-artefact gate (SEC-22). SEAM: UPLOAD-01 magic-byte content validation, UPLOAD-04 malware scanning. |
| **APIX** (API surface) | **PARTIAL** | APIX-02 upstream-untrusted (output-schema validation, SEC-21) + APIX-05 error hygiene (built). SEAM: APIX-01 surface inventory/versioning, APIX-03 bulk-extraction limits. |
| **TEN** (multi-tenancy) | **BUILT + SEAM** | TEN-01 code isolation (SEC-09, hostile-tenant tested); RLS (TEN-01 depth) + per-tenant quotas (TEN-03) are deploy/infra seams. |
| **PIPE** (CI/CD) | **SEAM** | Hardened pipeline, keyless deploy, artifact signing/admission, required gates - all CI/ops; the billing block is the live blocker. |
| **CONV** (conversation/memory) | **BUILT** | CONV-01/02 poisoning screen at ingestion (SEC-42), CONV-03 scope-controlled retrieval (SEC-40), CONV-04 residency (SEC-43), CONV-05 conversation confidentiality (SEC-25). |
| **PRIV** (privacy/provider) | **PARTIAL + SEAM** | PRIV-04 retention/erasure + PRIV-05 PII minimisation/redaction (built); PRIV-03 audit-access control (scope-filtered). SEAM: PRIV-01 DPIA/data-flow map, PRIV-02 provider zero-retention contracts (legal/ops). |
| **IDP** (federation/PAM) | **PARTIAL + HARDENED** | IDP-01 single issuer + per-service audience (auth, hardened with SEC-59); IDP-02 claim-mapping is change-controlled config. SEAM: IDP-04 break-glass PAM, IDP-05 de-provisioning propagation (IdP/ops). |
| **FOR** (forensics) | **PARTIAL + SEAM** | FOR-02 correlation/run-ids (the audit execution tree, built). SEAM: FOR-01 WORM/centralised logs, FOR-03 canaries, FOR-05 approval-integrity signals (detection/ops). |
| **GOV** (governance) | **PARTIAL + SEAM** | GOV-04 manifest-as-source-of-truth drift aid (built); the rest (vendor risk, disclosure policy, periodic assessment) is process/ops. |

## What this round built (the code gaps), all bound at debt 0

SEC-58 edge/web hardening (headers/CORS/Host/body-cap), SEC-59 JWT alg
allowlist + access-token-only + exp-required, SEC-60 dev-auth-refuses-prod, SEC-61
shared egress/IMDS guard for all HTTP adapters, SEC-62 id normalization
(anti-homoglyph grant bypass), SEC-63 webhook replay window. Plus the consolidated
egress guard module (`nankle/adapters/egress.py`) and constant-time PAT compare.

## The honest residue (NOT built here - seams)

- **Cloud (Azure):** managed identity, Key Vault, private endpoints, NSG/firewall
  egress, WAF/DDoS, Defender/Sentinel - needs an Azure subscription + IaC.
- **Host:** CIS baseline, rootless/user-ns containers, bastion, auditd - host/ops.
- **CI/CD (SUP/PIPE):** pinned/hash-locked deps + SCA + secret/image scan + SBOM +
  signing + required gates; **the GitHub Actions billing block is the live blocker
  (Principal)**.
- **Container hardening (INF-01):** non-root/read-only/cap-drop in the Dockerfiles
  is a buildable follow-on (next code round), not done here.
- **TLS/at-rest/RLS:** the secure compose overlay + a least-privilege DB role +
  Postgres RLS policies - a buildable+deploy follow-on.
- **Pi runtime (PI-01/02/03):** real native-tool-disable + micro-VM isolation
  land when the real Pi loop replaces the first-party stand-in.

These remain tracked here; each becomes BUILT only when its invariant is bound or
its environment is provided. This ledger is the source of truth for security
state - keep it accurate (AGENTS.md honesty rule).
