# Audit and compliance

## The tamper-evident audit chain

Every kernel action writes exactly one append-only audit row in the same logical step as the effect. Each row chains to the previous row's hash **per tenant** (an HMAC-SHA256 over a canonical serialisation of the row, keyed by `BOLTRIG_AUDIT_HMAC_KEY`), so any reorder, drop, or edit is detectable by re-deriving the chain. The read-head-to-append step is serialised per tenant (one lock; a Postgres `UNIQUE(tenant_id, seq)` is the multi-process backstop) so two concurrent writes cannot both claim the same sequence number or fork the chain.

**Set `BOLTRIG_AUDIT_HMAC_KEY` to a long random per-deployment value** (genesis fills a blank one for you; the built-in fallback is a dev-insecure placeholder). The chain's integrity rests on this key.

### What a row records

A row carries: tenant, sequence, timestamp, run/parent-run ids, actor + actor tier (`human`, `tier1`, `tier2`, `ephemeral`), depth, action type, noun, verb, target adapter, `on_behalf_of` (the delegated human identity), status, latency, tokens, cost, skills loaded, a scrubbed `detail`, and the chain fields (`seq`, `prev_hash`, `hash`). Enrichment fields (all nullable, folded into the hash only when present): `ip_address`, `user_agent`, `resource`, `resource_id`, `workspace_id`. This depth applies to MCP callers too - a call arriving over MCP is dispatched through the same chokepoint and audited with the same fields (and a bad/expired MCP run token is recorded as a security signal, see below).

### Bounded observability (never an exfiltration surface)

The writer scrubs `detail` before persisting: any string value carrying a secret or identity pattern is replaced by a digest + size + bounded preview, and long strings are truncated. Audit rows are "keys-only" by construction - a password, a session secret, an invite token, or a raw AI key is never written verbatim.

## The SecurityEvent stream

Security-relevant **signals** live on a distinct, separately-chained stream (not diluted into the business audit trail), using the same per-tenant hash-chaining pattern. Event types:

- `login_failure` - a rejected credential (with ip / user-agent).
- `rate_limit_trip` - a login throttle trip.
- `permission_denied` - a denied grant.
- `mcp_auth_failure` - a bad or expired MCP run token.

Signals are keys-only too: a row never carries a secret, password, or session token.

## The rollup anchor

A periodic rollup anchor covers a contiguous audit-chain segment: its root hash is a deterministic digest over the row hashes in the segment, letting a verifier confirm a segment has not been rewritten. Anchors are per tenant (optionally per workspace).

The shipping build writes a **local dev-fallback** anchor with no external call (`is_dev_fallback = true`), leaving the external-timestamp fields NULL.

**Not-yet-wired (Principal dependency):** external anchoring via an RFC3161 TSA timestamp (`rfc3161_token`) and an external KMS signature (`kms_signature`) is a clean seam that is documented but never called live. It activates only when a Principal wires the external credentials - set `BOLTRIG_AUDIT_TSA_URL` and/or `BOLTRIG_AUDIT_KMS_KEY_ID`. Until then anchors are local-fallback only and those two fields stay NULL.

## Search the trail

`GET /v1/audit/search` filters the business audit log by `actor`, `verb`, `run`, `resource`, and a `since` / `until` date range (a bare `YYYY-MM-DD` upper bound is treated as inclusive end-of-day). Set `security=1` to pivot to the SecurityEvent stream, optionally filtered by `event_type`. Reads are org/workspace-scoped fail-closed: a caller with an active workspace sees only org-wide rows plus its own workspace's rows, and department scoping hides other departments' runs.

```bash
curl -s "http://localhost:8080/v1/audit/search?actor=jane@acme.com&since=2026-07-01" \
  --cookie "boltrig_session=..."

curl -s "http://localhost:8080/v1/audit/search?security=1&event_type=login_failure" \
  --cookie "boltrig_session=..."
```

Related read routes: `GET /v1/cost` (cost by actor), `GET /v1/budgets` (live burn-down), `GET /v1/capabilities/changelog` (who changed capability, from `authoring.*` rows; author/admin only), `GET /v1/runs`, and `GET /v1/me/activity` (your own events). `POST /v1/audit/export` exports the full trail (author/admin only).

## Verify the chain

`GET /v1/audit/verify` recomputes the whole audit hash chain and the SecurityEvent chain, and checks the latest rollup anchor, reporting each as intact or broken (with the first bad sequence number where a break is found). Author/admin gated - integrity status is not for every member. Pass `?workspace=<id>` to narrow the anchor check to one workspace.

```bash
curl -s http://localhost:8080/v1/audit/verify --cookie "boltrig_session=..."
```

Response fields include `chain_intact`, `chain_first_bad_seq`, `security_chain_intact`, `security_first_bad_seq`, `anchor_intact`, the anchor record (including `is_dev_fallback`, and the NULL-until-wired `rfc3161_token` / `kms_signature`), and an overall `intact` boolean.
