# `/readyz` reports a live dependency as "disabled"

Date: 2026-07-26. Observed on the Classical Visas production tenant. **Not fixed** - the fix is
recorded here with the reason it was not landed in the same pass.

## The finding

CV's `/readyz`:

```json
{"status": "ready", "checks": {..., "model_gateway": "disabled"}}
```

But the gateway is not disabled. It is load-bearing:

```
BOLTRIG_MODEL_GATEWAY_URL       = http://bifrost:8080/v1     <- every agent turn routes here
BOLTRIG_MODEL_GATEWAY_HEALTH    = unset
BOLTRIG_MODEL_GATEWAY_HEALTH_URL= unset
```

`ReadinessService._model_gateway_enabled` (`boltrig/api/readiness.py`) keys the check on
`BOLTRIG_MODEL_GATEWAY_HEALTH` / `_HEALTH_URL` - the health-probe opt-ins - and NOT on
`BOLTRIG_MODEL_GATEWAY_URL`, which is what puts the gateway in the request path. So a stack that
routes every model call through bifrost reports the gateway `disabled`, `required: false`, and the
stack reads **ready** with bifrost face-down and every agent turn failing.

## Why the word matters

`disabled` is indistinguishable from "this stack uses no model gateway". An operator reading it
concludes there is nothing to check. The true state is "there IS one, and nothing is watching it" -
a different fact, and the one that would explain an outage.

This is the same shape as the other three found today: the audit chain that verified OK under a
public key, retention recorded BUILT with zero callers, an approval at `consumed` whose write had
failed. In each the reported state was green and the real state was not. See
[the standing rule](../../../Jellytot/docs/GOAL-long-horizon.md) - a green check is not evidence.

## The fix, and why it is not in this commit

Two separable changes, and only the second is a judgement call:

1. **Reporting (safe).** When `BOLTRIG_MODEL_GATEWAY_URL` is configured but no probe is enabled,
   report `status: "unchecked"`, `reason: "configured_but_health_check_disabled"` instead of
   `disabled`. `required` stays `false`, so no stack's readiness OUTCOME changes - only the record
   stops mislabelling a live dependency. Written, tested (including a seeded failure proving the
   old value fails the new test), and then reverted:

   `boltrig/api/readiness.py` is at **400/400**, the structure ratchet's hard file limit, so it
   cannot take a single line. Landing the change needs the gateway branch EXTRACTED to another
   module (`fleet/model_gateway.py` is the natural home; `api -> fleet` is already an allowed
   direction). Recording a new exemption instead was rejected: the ratchet is downward-only and
   this file was clean, so an exemption would be booking new debt to avoid a refactor.

   Deferred rather than rushed because the change is reporting-only, and the tree was contended by
   a concurrent session mid-edit in the same gate scripts.

2. **Gating (a real decision, NOT taken).** Should a configured gateway be `required: true`?
   Arguments both ways: it IS the dependency the agent needs, so a stack without it is not
   meaningfully ready; but promoting it would flip live stacks to `not_ready` on a bifrost blip and
   change what orchestration does with them. That is a deployment-contract change, not a reporting
   one, and belongs to whoever owns the readiness contract.

## Reproduce

```bash
docker exec cv-boltrig-kernel-1 python -c "
import urllib.request, json
d = json.loads(urllib.request.urlopen('http://localhost:8000/readyz', timeout=5).read())
print(d['status'], {k: v.get('status') for k, v in d['checks'].items()})"
# -> ready {... 'model_gateway': 'disabled'}
docker exec cv-boltrig-kernel-1 printenv BOLTRIG_MODEL_GATEWAY_URL
# -> http://bifrost:8080/v1
```
