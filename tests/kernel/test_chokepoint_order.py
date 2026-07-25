"""Chokepoint-order pins: output validation, credential-resolution placement,
and audit-always on every failure path (SEC-21, SEC-05, SEC-16).

The fixed dispatch order is doctrine: params are validated before any side
effect, the credential is resolved only AFTER grant/HITL/rate-limit gates pass
(never for a call that dies at a gate), adapter output is validated before it
returns, and EVERY outcome - including rate-limited, schema-invalid, and
adapter-crashed calls - writes its audit row.
"""

import pytest

from boltrig.adapters.base import Result, VerbSpec
from boltrig.kernel import Kernel
from boltrig.models import (
    GrantMissing,
    GrantSet,
    InvocationContext,
    PendingHuman,
    RateLimited,
    SchemaValidationError,
    TenantPermissions,
)
from boltrig.store import InMemoryStore

T = "acme"


class StrictAdapter:
    """A verb with a real input/output schema, so a bad call can be failed at
    each stage: bad params (schema in), a tripped gate, a crashed adapter, or
    out-of-schema output (schema out)."""

    id = "strict"
    version = "1.0.0"
    runtime = "script"

    def __init__(
        self,
        *,
        broken_output: bool = False,
        boom: bool = False,
        rate_limit: dict | None = None,
    ) -> None:
        self.calls = 0
        self.broken_output = broken_output
        self.boom = boom
        self.rate_limit = rate_limit

    def describe(self):
        return [
            VerbSpec(
                verb_id="strict.do",
                noun_id="strict",
                input_schema={
                    "type": "object",
                    "properties": {"x": {"type": "string"}},
                    "required": ["x"],
                },
                output_schema={
                    "type": "object",
                    "properties": {"n": {"type": "integer"}},
                    "required": ["n"],
                },
                rate_limit=self.rate_limit,
            )
        ]

    async def execute(self, verb, params, credential, context):
        self.calls += 1
        if self.boom:
            raise RuntimeError("adapter exploded")
        return Result.success({"n": "not-an-integer"} if self.broken_output else {"n": self.calls})

    async def health(self):
        return "ok"


def _ctx(grants: tuple[str, ...] = ("strict.*",)) -> InvocationContext:
    return InvocationContext(tenant_id=T, grants=GrantSet.of(list(grants)), actor="t")


async def _kernel(adapter: StrictAdapter, *, blocking_verbs: set[str] | None = None) -> Kernel:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    k = Kernel(store, blocking_verbs=blocking_verbs)
    await k.register_adapter(T, adapter)
    return k


# --------------------------------------------------------------------------- #
# (a) output validation: out-of-schema adapter output never returns as ok.
# --------------------------------------------------------------------------- #
@pytest.mark.kernel
@pytest.mark.invariant("SEC-21")
async def test_out_of_schema_adapter_output_is_rejected():
    adapter = StrictAdapter(broken_output=True)
    k = await _kernel(adapter)
    with pytest.raises(SchemaValidationError):
        await k.invoke("strict", "strict.do", {"x": "y"}, _ctx())
    assert adapter.calls == 1  # the adapter ran; its bad output was caught after


# --------------------------------------------------------------------------- #
# (b) credential-resolution placement: no resolve for a call that dies at a gate.
# --------------------------------------------------------------------------- #
class RecordingResolver:
    """Wraps the kernel's credential resolver and counts resolutions."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.resolutions = 0

    async def resolve_for_adapter(self, tenant_id, adapter_id):
        self.resolutions += 1
        return await self._inner.resolve_for_adapter(tenant_id, adapter_id)

    async def resolve_run_scoped_params(self, tenant_id, params, *, run_id=None, owner=None):
        # SEC-181 run-scoped param references resolve at the same stage; they
        # are not adapter-credential resolutions, so they pass through uncounted.
        return await self._inner.resolve_run_scoped_params(
            tenant_id, params, run_id=run_id, owner=owner
        )

    async def resolve_run_scoped_credential(self, tenant_id, run_id, adapter_id, owner=None):
        # The per-run adapter-bearer override (permission-parity passthrough)
        # resolves at the same stage as resolve_for_adapter; it is an OVERRIDE of
        # the adapter credential, not an additional resolution, so it too passes
        # through uncounted (and is None absent a sealed bearer, as here).
        return await self._inner.resolve_run_scoped_credential(
            tenant_id, run_id, adapter_id, owner
        )


def _recording(k: Kernel) -> RecordingResolver:
    rec = RecordingResolver(k.credentials)
    k.dispatcher._creds = rec
    return rec


@pytest.mark.kernel
@pytest.mark.invariant("SEC-05")
async def test_credential_never_resolved_when_the_grant_check_fails():
    k = await _kernel(StrictAdapter())
    rec = _recording(k)
    with pytest.raises(GrantMissing):
        await k.invoke("strict", "strict.do", {"x": "y"}, _ctx(grants=()))
    assert rec.resolutions == 0


@pytest.mark.kernel
@pytest.mark.invariant("SEC-05")
async def test_credential_never_resolved_when_the_hitl_gate_pends():
    k = await _kernel(StrictAdapter(), blocking_verbs={"strict.do"})
    rec = _recording(k)
    with pytest.raises(PendingHuman):
        await k.invoke("strict", "strict.do", {"x": "y"}, _ctx())
    assert rec.resolutions == 0


@pytest.mark.kernel
@pytest.mark.invariant("SEC-05")
async def test_credential_never_resolved_when_rate_limited():
    k = await _kernel(
        StrictAdapter(rate_limit={"per": "minute", "max": 1, "scope": "tenant"})
    )
    rec = _recording(k)
    await k.invoke("strict", "strict.do", {"x": "y"}, _ctx())
    assert rec.resolutions == 1  # the passing call resolves exactly once
    with pytest.raises(RateLimited):
        await k.invoke("strict", "strict.do", {"x": "y"}, _ctx())
    assert rec.resolutions == 1  # the tripped call never reached resolution


# --------------------------------------------------------------------------- #
# (c) audit-always: every failure path still writes its audit row.
# --------------------------------------------------------------------------- #
@pytest.mark.kernel
@pytest.mark.invariant("SEC-16")
async def test_rate_limited_dispatch_is_audited():
    k = await _kernel(
        StrictAdapter(rate_limit={"per": "minute", "max": 1, "scope": "tenant"})
    )
    await k.invoke("strict", "strict.do", {"x": "y"}, _ctx())
    with pytest.raises(RateLimited):
        await k.invoke("strict", "strict.do", {"x": "y"}, _ctx())
    events = await k.store.audit_query(T)
    assert [e.status for e in events] == ["ok", "rate_limited"]


@pytest.mark.kernel
@pytest.mark.invariant("SEC-16")
async def test_schema_invalid_dispatch_is_audited():
    k = await _kernel(StrictAdapter())
    with pytest.raises(SchemaValidationError):
        await k.invoke("strict", "strict.do", {}, _ctx())  # missing required "x"
    events = await k.store.audit_query(T)
    assert [e.status for e in events] == ["schema_invalid"]


@pytest.mark.kernel
@pytest.mark.invariant("SEC-16")
async def test_adapter_exception_dispatch_is_audited():
    k = await _kernel(StrictAdapter(boom=True))
    with pytest.raises(RuntimeError):
        await k.invoke("strict", "strict.do", {"x": "y"}, _ctx())
    events = await k.store.audit_query(T)
    assert [e.status for e in events] == ["error"]
