"""Adapter-native failures retain useful, transport-safe HTTP semantics."""

from __future__ import annotations

import pytest

from boltrig.adapters.base import AdapterError, Credential, ErrorClass, Result, VerbSpec
from boltrig.kernel import Kernel
from boltrig.models import AdapterFailure, GrantSet, InvocationContext, TenantPermissions
from boltrig.store import InMemoryStore

TENANT = "adapter-errors"


class RejectingAdapter:
    id = "rejecting"
    version = "1"
    runtime = "script"
    source = "test"

    def describe(self) -> list[VerbSpec]:
        return [
            VerbSpec(
                verb_id=f"errors.{kind.value}",
                noun_id="errors",
                input_schema={"type": "object"},
                output_schema={"type": "object"},
            )
            for kind in ErrorClass
            if kind not in {ErrorClass.RATE_LIMITED, ErrorClass.UNAVAILABLE}
        ]

    async def execute(
        self,
        verb: str,
        params: dict,
        credential: Credential | None,
        context: InvocationContext,
    ) -> Result:
        return Result.failure(AdapterError(ErrorClass(verb.removeprefix("errors.")), "rejected"))

    async def health(self) -> str:
        return "ok"


@pytest.mark.kernel
@pytest.mark.invariant("NFR-REL-04")
@pytest.mark.parametrize(
    ("kind", "status_code", "reason"),
    [
        (ErrorClass.NOT_FOUND, 404, "adapter_not_found"),
        (ErrorClass.UNAUTHORISED, 403, "adapter_unauthorised"),
        (ErrorClass.INVALID, 400, "adapter_invalid"),
        (ErrorClass.CONFLICT, 409, "adapter_conflict"),
        (ErrorClass.INTERNAL, 502, "adapter_internal"),
    ],
)
async def test_adapter_error_class_maps_to_safe_transport_error(
    kind: ErrorClass, status_code: int, reason: str
) -> None:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(TENANT, GrantSet.of(["errors.*"])))
    kernel = Kernel(store)
    await kernel.register_adapter(TENANT, RejectingAdapter())
    context = InvocationContext(
        tenant_id=TENANT,
        grants=GrantSet.of(["errors.*"]),
        actor="test",
    )

    with pytest.raises(AdapterFailure) as caught:
        await kernel.invoke("errors", f"errors.{kind.value}", {}, context)

    assert caught.value.status_code == status_code
    assert caught.value.reason == reason
