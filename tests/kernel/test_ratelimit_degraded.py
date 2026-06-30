"""Rate limiting (FR-KER-05) and graceful degradation (US-KER-06, P9)."""

import pytest

from boltrig.models import DegradedMode, RateLimited, RateLimit, TargetType, VerbBinding
from tests.conftest import TENANT, make_ctx


@pytest.mark.kernel
@pytest.mark.invariant("FR-KER-05")
async def test_rate_limit_enforced(kernel):
    # tighten ticket.create to 2/minute
    await kernel.store.upsert_binding(
        VerbBinding(
            verb_id="ticket.create",
            tenant_id=TENANT,
            target_type=TargetType.ADAPTER,
            target_ref="memory-tickets",
            rate_limit=RateLimit(per="minute", max=2, scope="tenant"),
        )
    )
    for _ in range(2):
        await kernel.invoke(
            "ticket", "ticket.create", {"title": "x"}, make_ctx(["ticket.create"])
        )
    with pytest.raises(RateLimited):
        await kernel.invoke(
            "ticket", "ticket.create", {"title": "x"}, make_ctx(["ticket.create"])
        )


@pytest.mark.kernel
@pytest.mark.invariant("P9")
async def test_degraded_mode_when_backend_down(kernel_and_adapter):
    kernel, adapter = kernel_and_adapter
    adapter._fail = True  # simulate backend outage
    with pytest.raises(DegradedMode) as exc:
        await kernel.invoke(
            "ticket", "ticket.create", {"title": "x"}, make_ctx(["ticket.create"])
        )
    assert exc.value.output["_degraded"]["reason"] == "backend_unavailable"
    assert exc.value.deferred is True
