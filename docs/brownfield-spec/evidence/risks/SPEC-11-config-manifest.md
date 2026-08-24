# Risks harvested from SPEC-11-config-manifest.md

RISK-1: **The `dev_egress_loopback` manifest key can never be read.**
`build_diversion_resolver` asks for `manifest.section("dev_egress_loopback")`
([`boltrig/kernel/dev_egress_runtime.py:84`](../../../boltrig/kernel/dev_egress_runtime.py) `section = manifest.section("dev_egress_loopback")`),
but `FleetManifest.extra` is built from a closed fourteen-name tuple that does
not contain it
([`boltrig/config/manifest.py:862`](../../../boltrig/config/manifest.py) `"extra={k: doc[k] for k in ("`),
so `section()` returns `{}` for every real manifest and the resolver is
permanently `DiversionResolver(None)`. The whole court-permitted feature is
unreachable from a manifest. Its tests never notice because they hand
`build_diversion_resolver` a stub whose `section()` answers any name
([`tests/security/test_dev_egress_loopback.py:178`](../../../tests/security/test_dev_egress_loopback.py) `"def section(self, _name):"`),
and the unwired-claims gate cannot see it because the block is commented out in
the template. Bounded: `extra` is assigned in exactly one place
(`rg -n "extra={" boltrig/config/manifest.py`), `effective_manifest_from_desired`
uses `dataclasses.replace` and preserves it, and every other `.section()` caller
names a key that IS in the tuple (`rg -n "\.section\(" --glob '!tests/**'`),
2026-08-24, pinned tree.

---

RISK-2: **The API serving process holds three manifest reads, not one.**
`CODEX-COMPOSITION-1` says "at most one manifest snapshot"; the API composes one
at import, re-reads the file in `chat_factory` at lifespan startup
([`boltrig/api/bootstrap.py:590`](../../../boltrig/api/bootstrap.py) `"chat_cfg = load_manifest(manifest_path).chat"`)
and opens it a third time, uninterpolated, for `AdminConfig`
([`boltrig/api/platform_bootstrap.py:110`](../../../boltrig/api/platform_bootstrap.py) `"admin = AdminConfig(kernel.store, tenant_id=tenant, path=manifest_path)"`).
A file changed between import and lifespan therefore splits the API's kernel
policy from the API's chat policy, and the birth-profile digest cannot detect it
because only the composition snapshot enters `manifest_generation`. The
invariant's own test monkeypatches `_build_chat_wiring` away, so this path is
never exercised
([`tests/unit/test_codex_trusted_composition.py:278`](../../../tests/unit/test_codex_trusted_composition.py) `"_build_chat_wiring"`).

---

RISK-3: **The shipped example manifest carries the exact approval window a court
found harmful.** `hitl.approval_timeout_seconds: 3600`
([`manifest.example.yaml:325`](../../../manifest.example.yaml) `"approval_timeout_seconds: 3600"`),
while the code's floor is 86400 and its comment records that one hour "is the
actual proximate cause of what was experienced as deadlock"
([`boltrig/config/manifest.py:204`](../../../boltrig/config/manifest.py) `"is the actual proximate cause of what was"`).
A stated value is honoured unclamped by design, and `genesis.sh` copies this file
to `manifest.yaml` verbatim, so every genesis-provisioned tenant starts on the
one-hour window unless someone edits it.

---

RISK-4: **`genesis.sh` mints the audit key but not the seal key.** It calls
`gen_secret` for `POSTGRES_PASSWORD` and `BOLTRIG_AUDIT_HMAC_KEY` and
`gen_ed25519_seed` for the device lease key
([`genesis.sh:104`](../../../genesis.sh) `"gen_secret BOLTRIG_AUDIT_HMAC_KEY"`),
and never touches `BOLTRIG_SEAL_KEY` (bounded: `grep -n "SEAL_KEY" genesis.sh`
returns nothing, 2026-08-24). Genesis also sets no production signal, so
`_active_fernets` takes the fall-back branch and every `credential_refs` row is
sealed with the in-source `dev-insecure-seal-key`, which is plaintext-equivalent
at rest to anyone with this repository.

---

RISK-5: **The stock template boots a model endpoint with an empty model name.**
`model: ${BOLTRIG_DEFAULT_MODEL:-}`
([`manifest.example.yaml:69`](../../../manifest.example.yaml) `"model: ${BOLTRIG_DEFAULT_MODEL:-}"`)
and `BOLTRIG_DEFAULT_MODEL` appears nowhere in `.env.example`. `ModelEndpoint`
does not validate `model` for emptiness, and `_check_model_posture` counts
endpoints and checks the sensitive route but never checks that an endpoint names
a model (bounded: `grep -n "\.model\b" boltrig/api/doctor.py` returns nothing,
2026-08-24). The intent is deliberate (bring your own Bifrost) but the failure
surfaces only at the first model call.

---

RISK-6: **The manifest comment that `credential_ref` "is never
`${ENV}`-interpolated" is not a property of the loader.** `_interpolate` walks
the WHOLE document before any parsing
([`boltrig/config/manifest.py:442`](../../../boltrig/config/manifest.py) `"def _interpolate(obj: Any, env: Mapping[str, str]) -> Any:"`),
so `credential_ref: ${LINEAR_MCP_TOKEN}` is substituted with the token VALUE and
that value is then written into `credential_refs` as the lookup key
([`boltrig/config/control_mcp.py:79`](../../../boltrig/config/control_mcp.py) `"ref=ref,"`).
`bind_mcp_credential` refuses only the legacy `token` and `credential` keys and
cannot detect plaintext arriving through `credential_ref`
([`boltrig/config/control_mcp.py:70`](../../../boltrig/config/control_mcp.py) `"passes raw secret material; use 'credential_ref'"`).
The same shape applies to `adapters[].credential.ref`.

---

RISK-7: **`config-validate` documents a false-red it cannot produce.** The
module's own contract promises a failure on an unset `${VAR}` naming the variable
([`boltrig/api/config_validate.py:33`](../../../boltrig/api/config_validate.py) `"That failure direction is safe (a"`);
`_interpolate` substitutes the empty string and never raises. An operator who
follows that paragraph will believe a bare run proves more than it does.

---

RISK-8: **Routine chat inside the API gets no manifest chat policy.**
`register_boltrig_tasks` builds a second `ChatService` with `chat_config`
omitted
([`boltrig/fleet/hatchet_app.py:241`](../../../boltrig/fleet/hatchet_app.py) `"routine_chat = _routine_chat_service(kernel, spawner) if spawner is not None else None"`),
and `ChatService` then uses a bare `ChatConfig()`
([`boltrig/fleet/chat.py:91`](../../../boltrig/fleet/chat.py) `"self._cfg = chat_config if chat_config is not None else ChatConfig()"`),
i.e. the code-default MAXIMUM caps. A manifest that TIGHTENS an attachment or
pagination cap is therefore not honoured on the workflow-driven routine path in
the API process, while the Hatchet worker's equivalent does thread
`manifest.chat`.

---

RISK-9: **Thirty-seven `BOLTRIG_*` variables that shipped code reads are
documented nowhere in the operator-facing files** (7.1). Three of them
(`BOLTRIG_AUTH_MODE`, `BOLTRIG_SESSION_TENANT`, `BOLTRIG_SESSION_COOKIE_SECURE`)
are the entire first-party login posture, and one (`BOLTRIG_MANIFEST`) silently
changes which tenant the whole stack serves.

---

RISK-10: **`manifest.example.yaml` is a live boot fallback outside a container.**
It is the last candidate in `_MANIFEST_CANDIDATES`
([`boltrig/api/bootstrap.py:52`](../../../boltrig/api/bootstrap.py) `"manifest.example.yaml",`),
so a source-tree run with no `manifest.yaml` boots the template tenant
(`tenant_id: ${BOLTRIG_TENANT_ID:-default}`) complete with its 3600-second
approval window, rather than the loud `no manifest found` demo path. Inside the
shipped images the file is absent, so the exposure is developer boxes and any
non-Compose source deployment.

---

RISK-11: **The unwired-claims manifest gate is a bare-name substring match over
one boolean form.** `unread_manifest_keys` matches `\bkey\b` against the
concatenation of every Python source
([`scripts/check_unwired_claims.py:313`](../../../scripts/check_unwired_claims.py) `"if not re.search(rf"`),
so a knob named `enabled`, `panel` or `continuity` passes on any unrelated
occurrence anywhere in the tree, and only `key: true|false` lines are considered
at all. It proves the absence of a name, not the presence of a reader.

---

RISK-12: **`_HMAC_KEY` is bound at module import.**
([`boltrig/kernel/audit.py:28`](../../../boltrig/kernel/audit.py) `_HMAC_KEY = os.environ.get("BOLTRIG_AUDIT_HMAC_KEY", "dev-insecure-audit-key").encode()`)
Any environment mutation after `boltrig.kernel.audit` is imported, including one
by a test fixture or a future `export_runtime_environment` extension, is not
observed by the audit chain while `refuse_default_audit_key_in_prod` reads the
LIVE environment. The two can disagree.

---
