# Arc-1 preflight + security findings

Synthesis of the deterministic wave (4a) + the security-methodology reasoning (4b)
over the `boltrig/` package (110 files, 1040 functions, ~17.2k LOC). Findings are
deduped by `(file, line, rule)` and ranked by risk, not ease of fix.

## Headline

**No Critical or High security findings.** The arc is STRUCTURAL, not
security-driven: 8 files over the 400-LOC floor and 55 functions over the function
floor. The security posture is sound (chokepoint intact, credentials kernel-only,
multi-tenant isolation via RLS + kernel-authoritative identity). The findings below
are hardening, a confirmed false-positive, and the structural debt that defines the
arc's scope.

---

## Security findings

### SEC-001 (False-positive-risk, Low) bandit B608 on `store/postgres.py:428` — CONFIRMED FALSE POSITIVE

- **surface:** sql-data-access
- **confidence:** Confirmed (false positive)
- **evidence:** `boltrig/store/postgres.py:428` — `f"SELECT * FROM work_items WHERE {' AND '.join(clauses)}"`.
  `clauses` holds positional placeholders (`parent_id=$1`, `owner_member = ANY($2::text[])`); all values
  pass via `*args`. The f-string interpolates only placeholder indices, never user data.
- **exploit_scenario:** None — bandit's heuristic flags any f-string in a SQL call; here the shape is
  "dynamic query + bound args", the safe pattern.
- **suggested_fix:** No code change. Add a `# nosec B608` with a one-line justification, OR (preferred) leave
  it and track here so future runs don't re-triage. The codebase has no string-interpolated user data into SQL
  anywhere (grep-verified: all `self._pool.execute/fetchrow` use `$N` placeholders + args).
- **required_verification:** none.
- **residual_risk:** None.

### SEC-002 (Low) dev CLI binds 0.0.0.0 (bandit B104)

- **surface:** availability-resource-exhaustion
- **confidence:** Confirmed
- **evidence:** `boltrig/api/cli.py:31` binds all interfaces. Intended for the local dev/console server;
  production is behind Caddy + Cloudflare (zero-trust edge), not this CLI.
- **suggested_fix:** Bind `127.0.0.1` by default; require an explicit `--host 0.0.0.0` to bind wide. Low
  impact (dev-only surface) but removes the foot-gun.
- **required_verification:** `cli.py` still boots; the console smoke test stays green.
- **residual_risk:** Minimal (prod ingress is Caddy, not this bind).

### SEC-003 (Low) `delete_binding` ignores the path `channel_id`

- **surface:** authz-tenant
- **confidence:** Confirmed
- **evidence:** `kernel/channel_routes.py:358` `DELETE /v1/channels/{channel_id}/bindings/{binding_id}`
  calls `delete_channel_binding(tenant_id, binding_id)` without asserting the binding belongs to
  `channel_id`. Tenant-scoped + admin-gated, so not a cross-tenant hole, but the path param is decorative.
- **suggested_fix:** Verify the binding's `channel_id == channel_id` before delete (return 404 otherwise),
  for REST consistency and to keep the audit row honest.
- **required_verification:** add a unit test: deleting a binding under the wrong channel 404s.
- **residual_risk:** None (tenant boundary holds).

### SEC-004 (Info, defense-in-depth) posture confirmations

- **surface:** multiple
- **confidence:** Confirmed
- **evidence (all green):**
  - Chokepoint order intact: `kernel/dispatch.py:180` `_invoke_inner` runs resolve → validate → grant →
    HITL → rate → idempotency → execute → validate-output, with credentials resolved kernel-side
    (`_creds.resolve_for_adapter`, `_execute_adapter`), never handed to an agent.
  - No dangerous sinks: grep for `eval(`/`exec(`/`shell=True`/`pickle.load`/`yaml.load(`/`verify=False`/
    `os.system` in `boltrig/` finds only named methods and a blocklist string literal — no real sinks.
  - No hard-coded secret-shaped literals in the package.
  - Secrets never logged: `adapters/base.py:26` `Credential` is `repr=False` + `__str__`-scrubbed; the audit
    redacts (SEC-05); memory ingestion blocks API secrets fail-closed (`memory/adapter.py` SEC-42).
  - Channel identity is kernel-authoritative: tenant from the verified channel, role from the RLS binding,
    never the payload; unbound senders denied fail-closed (`kernel/channel_gateway.py`,
    `kernel/channel_routes.py`). All mutating channel routes are admin-gated (`_admin(p)`), ingress is
    signature-authenticated with no principal.
  - Dependency posture clean: `pip-audit` 0 PyPI vulns; `semgrep p/python` 0 findings.
- **suggested_fix:** none.
- **residual_risk:** SOC 2 ripgrep script not authored (see tool-skip-log) — compliance evidence gap, not a
  code defect.

---

## Structural findings (define the arc scope)

Source: `pre-arc/atomize.json` (AST McCabe substitute for vibeclean). Floor: file
≤400 LOC, function ≤80 LOC, cc ≤15, nesting ≤4, params ≤5.

### STR-001: 8 files over the 400-LOC floor (Tier-3 god files)

| file | LOC | note |
|---|---|---|
| `store/postgres.py` | 1482 | one row-op per SQL method, grouped by domain — decompose by DOMAIN into a `store/pg/` partial package, do NOT chop at 400 |
| `config/manifest.py` | 580 | manifest seeding — extract per-domain seeders |
| `store/memory.py` | 579 | symmetric twin of postgres — split in lockstep, same domain sections |
| `kernel/platform_routes.py` | 576 | route closures — extract routes to module-level fns |
| `fleet/spawn.py` | 565 | skill-merge + fleet spawn — extract skill-resolution |
| `adapters/generator.py` | 535 | adapter codegen — extract per-runtime generators |
| `kernel/app.py` | 511 | `create_app()` god-fn (370 LOC/cc41/9 params) — extract route-registration blocks |
| `adapters/http_base.py` | 444 | HTTP adapter base — extract retry/pagination/egress sections |

### STR-002: the `register_*_routes` closures are the worst complexity (cc 38–69)

`register_platform_routes` (cc 69), `register_channel_routes` (cc 57),
`register_access_routes` (cc 38), `register_memory_routes` (cc 14). Each route is a
nested closure, so the "function" is really a route-registration block. The
mechanical, behaviour-preserving fix is the same for all: hoist each route handler
to a module-level `async def` taking explicit `kernel`/`principal` deps, leaving a
thin `register_*` that only wires `app.add_api_route`. This drops cc to ~1 per
handler and the register fn to a flat list. **Highest ROI structural move in the
arc; do it first as the round-1 pattern.**

### STR-003: 55 functions over the function floor

Top offenders beyond the route closures: `create_app()` (370/cc41/9p),
`spawn()` (147/cc17/8p), `run_workflow_definition()` (108/cc23/6p),
`recall()` pgvector (83/cc19/7p), `_invoke_inner` (71/cc16/8p),
`pi_runtime.run()` (53/cc19/nest7), `parse_skill()` (76/cc23),
`apply_manifest()` (75/cc17). Full list in `pre-arc/atomize.json`.

### STR-004: lint debt (2 ruff findings)

`scripts/cf-wire-boltrig.py:14` E401, `tests/security/test_round_three.py:143`
E702. Trivial; fix as housekeeping, not arc work.

---

## Deferred (NORMAL-mode followups, not bundled with structural commits)

- SEC-002 (cli bind), SEC-003 (binding channel_id), STR-004 (ruff) — small, land as
  a single housekeeping commit before round-1 dispatch.
- Author `scripts/audit-soc2-compliance.sh` (SOC 2 evidence gap).
- Repair or remove the broken `vibeclean`/`vibescan` installs (tooling gap).
