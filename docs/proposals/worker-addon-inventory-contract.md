# Worker add-on inventory contract

Status: implemented on 2026-07-29.

The finding below records the pre-implementation gap. The authenticated route,
shared SDK method and Worker **Runtime add-ons** section now implement this
contract; the required coverage at the end is executable.

## Finding

Worker cannot currently show an honest installed/active add-on inventory.

Boltrig does have canonical process-local facts:

- `boltrig.addons.registered()` returns the add-ons loaded into this build;
- `boltrig.addons.active_addons()` resolves the deployment-wide
  `BOLTRIG_ADDONS` selection and fails startup on an unknown name; and
- every `Addon` has a canonical name and version, plus optional harness,
  adapter-id and consequence-hint contributions.

Those facts are consumed when the API and worker processes boot and are written
only to their logs. They are not projected through an authenticated route or the
shared web SDK. The existing nearby surfaces are not substitutes:

- `/healthz` exposes cached adapter health keyed by tenant and adapter, not
  add-on registration or activation;
- `/readyz` checks deployment dependencies and the control plane, not add-ons;
- `/v1/platform/status` reports runtime components supplied by the stack status
  provider; and
- `/v1/integrations/catalogue` and `/v1/integrations/connections` describe
  connectable provider accounts. An add-on may be harness-only and an
  integration connection may exist without being an add-on.

The current `Addon` declaration also has no configuration requirements or
readiness contract. Therefore neither the kernel nor Worker can truthfully turn
“registered and named in an environment variable” into “configured” or
“working”. Inferring add-ons from verbs, adapter records, prompt text or
integration connections would silently produce both false positives and false
negatives.

## Terminology boundary

This contract inventories the versioned extension seam in `boltrig.addons`.
Boltrig also uses “add-on” informally for three feature families which are not
registered there and must not be folded into this result by inference:

- Knowledge projections already have their own tenant-scoped canonical provider
  catalogue at `/v1/knowledge/providers`. Worker renders the shipped Cognee
  compiler from that contract, including its enabled, bundled, health and status
  fields. Retired provider rows are not public add-ons.
- The emotion relay is a process-level optional projection. It has an enable
  switch but no authenticated status/version/readiness projection.
- Legacy desktop hands is an opt-in set of verbs and a host pull route.
  Route/verb presence proves only that the server-side switch is on; it does not
  prove that the separate host executor is installed or healthy.

The external Wayland familiar is a consumer of the emotion/express stream, not a
Boltrig package installed through `boltrig.addons`.

Worker therefore needs two honest ideas:

1. **Runtime add-ons**, supplied by this proposed contract; and
2. feature-specific availability, supplied by each feature's canonical contract.

The first implementation must label the section **Runtime add-ons**, not the
unqualified **Add-ons**. A later product-wide feature-availability catalogue may
normalize those dedicated projections, but only after emotion and desktop hands
gain canonical readiness evidence. This route must not claim to be that
catalogue.

## Required declaration

Extend the add-on data declaration with requirements. Requirements are data, not
callbacks, and cannot add verbs, credentials or grants:

```python
AddonRequirement(
    id="opbox-adapter",
    kind="adapter",       # adapter | component | environment | credential_ref
    ref="opbox",          # evaluated inside the kernel; never returned verbatim
    required=True,
)
```

`Addon` gains:

```python
requirements: tuple[AddonRequirement, ...] = ()
```

Semantics:

- `adapter`: a tenant-scoped adapter record exists, is loaded, and its cached
  health is evaluated;
- `component`: the canonical stack-status component exists and its reported
  status is evaluated;
- `environment`: the named deployment setting is non-empty; only presence is
  observed and its name/value is never returned;
- `credential_ref`: the tenant has the named credential reference; no credential
  metadata or value is returned.

An add-on with no requirements is configuration-complete once active because
its declared contribution is fully load-time data. A requirement evaluator
must not perform provider I/O in a list request. Runtime checks use only
canonical persisted or cached evidence and identify that evidence honestly.

## Authenticated read contract

Add one read-only route:

```
GET /v1/addons
```

It requires an authenticated principal. It evaluates tenant-scoped requirements
against `principal.tenant_id` and `principal.active_workspace_id`; it never
accepts a tenant or workspace in query parameters. All tenant members may read
the bounded projection because it contains no secrets, prompt text, credential
references or deployment-variable names.

Exact response:

```json
{
  "scope": {
    "tenant_id": "tenant-1",
    "workspace_id": "workspace-1"
  },
  "addons": [
    {
      "id": "opbox",
      "version": "1.0.0",
      "installation": "installed",
      "activation": "active",
      "contributions": {
        "harness": true,
        "adapter": true,
        "consequence_hint": true
      },
      "configuration": {
        "status": "ready",
        "requirements": [
          {
            "id": "opbox-adapter",
            "kind": "adapter",
            "required": true,
            "status": "ready",
            "reason": null,
            "evidence": "cached_adapter_health"
          }
        ]
      },
      "runtime": {
        "status": "ready",
        "reason": null
      }
    }
  ]
}
```

Closed vocabularies:

- `installation`: `installed`;
- `activation`: `active | inactive`;
- requirement `status`: `ready | missing | degraded | unavailable | unverified`;
- requirement `reason`:
  `not_configured | record_missing | not_loaded | health_degraded |
  health_down | health_unverified | component_missing | credential_missing |
  evidence_unavailable | null`;
- requirement `evidence`:
  `declaration | configuration_presence | credential_reference |
  cached_adapter_health | stack_status`;
- `configuration.status`:
  `ready | missing | degraded | unavailable | unverified | not_required`; and
- `runtime.status`:
  `ready | degraded | unavailable | unverified | inactive`.

Aggregation is deterministic:

1. An inactive add-on has `runtime.status=inactive`. Its requirements may still
   report their observed state, but do not make the add-on active.
2. An active add-on with no requirements has
   `configuration.status=not_required` and `runtime.status=ready`.
3. Any required `missing` requirement makes configuration `missing` and runtime
   `unavailable`.
4. Otherwise any required `unavailable` requirement makes configuration and
   runtime `unavailable`.
5. Otherwise any required `unverified` requirement makes both `unverified`.
6. Otherwise any degraded requirement makes both `degraded`.
7. Otherwise configuration and runtime are `ready`.

The route lists every registered add-on, active or inactive, sorted by `id`.
Registration means installed in the running build; the API must not invent a
marketplace, available-for-download or deployment history.

`version` is the declared add-on version, not the composed Codex birth-profile
version. If the latter is needed later, add a separately named
`profile_version`; do not overload `version`.

## Failure and redaction

- A process still fails at boot when `BOLTRIG_ADDONS` names an unregistered
  add-on. The route is not a recovery path for an invalid deployment.
- A readiness evaluator failure returns the affected requirement as
  `unavailable/evidence_unavailable`; it does not fail the whole list or turn the
  result green.
- The response never includes harness text, environment names or values,
  credential ids or values, entry-point import paths, stack probe output, or
  exception text.
- The route is read-only. It has no activate, deactivate, install, remove,
  configure or credential mutation companion. Those remain deployment and
  governed control-plane concerns until separately designed.

## SDK and Worker surface

The shared SDK should add `addons(): Promise<AddonsResponse>`. Worker should call
only that method and render a **Runtime add-ons** section under Integrations:

- name and exact declared version;
- Installed/active or Installed/inactive;
- Ready, degraded, unavailable or unverified, with the server reason translated
  into plain language; and
- contribution badges for Agent guidance, Adapter binding and Risk mapping.

There must be no activation or configuration button. An unavailable endpoint is
shown as “Add-on inventory unavailable”, not an empty installed list. Loading,
denied, unavailable and canonical-empty states remain distinct.

## Invariant coverage

The implemented contract is pinned so that:

1. an authenticated tenant sees all and only the process registry, sorted and
   with exact declared versions;
2. inactive and active are derived from the same fail-closed resolver used at
   boot;
3. tenant-scoped adapter and credential evidence cannot cross tenants or
   workspaces;
4. requirement aggregation covers every closed status and cannot turn unknown
   evidence into ready;
5. response serialization excludes harnesses, environment/credential refs and
   exception text;
6. the route is bound in the backend-to-SDK-to-Worker route ledger; and
7. Worker tests pin loading, canonical empty, inactive, ready, degraded,
   unavailable, unverified, denied and API-unavailable states.
