# AI keys and models

## The key hierarchy: org, workspace, user

AI keys live in one unified `ai_configs` table, keyed by `(tenant_id, level, scope_id)` where level is one of `org`, `workspace`, `user`:

- `org` - scope_id is the tenant_id (the org id is the tenant boundary).
- `workspace` - scope_id is a workspace id.
- `user` - scope_id is a user id.

Each row holds a provider selection, a pinned model, an optional `base_url` (the provider's API host - routing metadata, not a secret), and a `credential_ref`. The **raw key is never stored in this row** - only the reference into the sealed credential store.

### Resolution precedence

At call time the kernel resolves which key a run uses:

```
user  ->  workspace  ->  org  ->  manifest/env default
```

The `default` level means no config applies and the run falls back to the manifest/env-configured provider key (every existing single-tenant deploy resolves here). Resolution is tenant-scoped: only rows inside the tenant are ever consulted, and the workspace considered is the caller's already-authorized active workspace.

## The `allow_own_ai_keys` gate

`allow_own_ai_keys` is an org-wide policy flag (default **false**, fail-closed). It gates whether workspace/user keys count at all:

- When **false**: workspace and user rows are ignored at resolution; only the **org** key (or the env/manifest default) is used. A member cannot bring their own key.
- When **true**: the full precedence holds - the caller's own user key wins, then their active workspace's key, then the org key, then the default.

The org key always applies regardless of the flag (an org may always set its own key). The flag is enforced both at write time (a workspace/user key that would be ignored is refused up front) and, load-bearingly, at resolution time. Toggle it with `PATCH /v1/orgs/current`.

## Who may set a key

`PUT /v1/ai-keys` authorizes by level:

- `org` - org-admin (`superadmin` / `admin` / `org-admin`).
- `workspace` - org-admin, or a workspace owner/admin of that workspace; **and** the org must allow own AI keys.
- `user` - org-admin, or the caller acting on their **own** user id; **and** the org must allow own AI keys.

```bash
curl -s -X PUT http://localhost:8080/v1/ai-keys \
  -H 'content-type: application/json' -H "x-boltrig-csrf: $CSRF" \
  --cookie "boltrig_session=...; boltrig_csrf=$CSRF" \
  -d '{"level":"org","provider":"anthropic","model":"claude-sonnet-4-6","api_key":"sk-..."}'
```

`scope_id` defaults sensibly (`org` -> the tenant, `user` -> the caller); a `workspace` level requires an explicit `scope_id`. `base_url` is optional.

List (never returns the key) and delete:

```bash
GET    /v1/ai-keys                         # provider/model + has_key only, plus allow_own_ai_keys
DELETE /v1/ai-keys/{level}/{scope_id}      # drops the config row and the sealed credential together
```

## The sealed-storage guarantee

A key is **never returned and never audited**:

- On `PUT`, the raw key is accepted once and stored only through the sealed credential store (`set_credential_ref`), keyed by an opaque generated `credential_ref`. There is no plaintext column on `ai_configs`.
- Listing returns provider, model, base_url and `has_key` (a boolean) - never the key.
- The audit row for a key set records level / scope / provider / model / base_url and the credential-ref id, never the `api_key` itself.
- At call time the kernel loads the material from the RLS-fenced credential store and hands it straight to one runtime call. It is never logged, returned to an agent, embedded in a result, or written to audit.

## Provider / model routing and the SEC-12 rule

When resolution returns a non-default row, the spawner selects the runtime by `provider` and pins the endpoint's `model` / `base_url`. Model endpoints and their routing are declared in the fleet manifest (`manifest.yaml`), each carrying a `data_class` of `standard` or `sensitive`:

```yaml
models:
  endpoints:
    - id: standard
      kind: anthropic
      model: claude-sonnet-4-6
      data_class: standard
    - id: local-sensitive
      kind: vllm
      base_url: http://local-model:8000/v1
      data_class: sensitive
  default: standard
  sensitive_endpoint: local-sensitive
```

**SEC-12 - sensitive data stays local.** The model-endpoint router guard enforces that sensitive-classified data may only reach a local (`data_class == "sensitive"`) endpoint. For sensitive data it returns the capability's own sensitive endpoint if local, else the configured `sensitive_endpoint`, and otherwise raises `SensitiveDataMisrouted` and audits the attempt - so sensitive content never egresses on a mistaken route. This overrides an AI-key resolution: even with a non-default provider selected, sensitive-classified data routes to the local endpoint regardless. `AIR_GAPPED=true` in `.env` forbids all outbound network and forces on-box inference.
