"""Per-run adapter bearer (the permission-parity passthrough): a caller's clamped
external bearer sealed for ONE adapter for ONE run resolves into the adapter
credential, is scoped fail-closed to that run+adapter, and - unlike a secure
answer - can NEVER be surfaced into a verb param (SEC-181 sibling, K-20)."""

import pytest

from boltrig.adapters.base import bearer_token
from boltrig.kernel.credentials import adapter_bearer_cred_id
from boltrig.models import CredentialResolution
from tests.conftest import TENANT

RUN = "run-parity-1"
TOKEN = "opbox-clamped-bearer-9f8e7d6c"


@pytest.mark.security
async def test_sealed_bearer_resolves_for_same_run_and_adapter(kernel):
    await kernel.credentials.seal_run_scoped_adapter_bearer(TENANT, RUN, "opbox", TOKEN)
    cred = await kernel.credentials.resolve_run_scoped_credential(TENANT, RUN, "opbox")
    assert cred is not None
    # The dispatch override hands this to the adapter, which derives the bearer.
    assert bearer_token(cred) == TOKEN


@pytest.mark.security
async def test_scoped_fail_closed_to_run_and_adapter(kernel):
    await kernel.credentials.seal_run_scoped_adapter_bearer(TENANT, RUN, "opbox", TOKEN)
    # A different run must not see it (another turn cannot borrow the bearer).
    assert await kernel.credentials.resolve_run_scoped_credential(TENANT, "run-other", "opbox") is None
    # A different adapter must not see it (the bearer never leaks past its adapter).
    assert await kernel.credentials.resolve_run_scoped_credential(TENANT, RUN, "jira") is None
    # A missing run id resolves to None (=> static credential fallback at dispatch).
    assert await kernel.credentials.resolve_run_scoped_credential(TENANT, None, "opbox") is None


@pytest.mark.security
async def test_unsealed_resolves_none_static_fallback(kernel):
    # Nothing sealed => None, so _execute_adapter keeps the static service credential.
    assert await kernel.credentials.resolve_run_scoped_credential(TENANT, RUN, "opbox") is None


@pytest.mark.security
@pytest.mark.invariant("K-20")
async def test_bearer_never_surfaced_through_param_resolver(kernel):
    """The adapter bearer shares the ``run:`` keyspace with secure answers, so a
    crafted ``credential:run/<run>/adapter_bearer:opbox`` reference in a verb
    param would resolve to the SAME sealed row. The distinct kind marker makes
    the param resolver fail closed instead of substituting the bearer - the only
    thing that keeps an agent from coaxing the bearer into an output."""
    await kernel.credentials.seal_run_scoped_adapter_bearer(TENANT, RUN, "opbox", TOKEN)
    crafted = f"credential:run/{RUN}/adapter_bearer:opbox"
    with pytest.raises(CredentialResolution):
        await kernel.credentials.resolve_run_scoped_params(
            TENANT, {"leak": crafted}, run_id=RUN
        )


@pytest.mark.security
async def test_swept_with_the_run(kernel):
    await kernel.credentials.seal_run_scoped_adapter_bearer(TENANT, RUN, "opbox", TOKEN)
    # Confirm it is sealed under the run keyspace, then the run-terminal sweep drops it.
    assert await kernel.store.get_credential_ref(TENANT, adapter_bearer_cred_id(RUN, "opbox")) is not None
    await kernel.credentials.sweep_run_scoped(TENANT, RUN)
    assert await kernel.credentials.resolve_run_scoped_credential(TENANT, RUN, "opbox") is None


# --- delegation: the seal must survive a spawn ------------------------------
# A chat turn seals against the ROOT run but never calls verbs itself: it spawns an
# ephemeral worker and the dispatch happens under the CHILD's run id, which
# resolve_run_scoped_credential is keyed by. Without propagation the child silently
# fell back to the adapter's static credential and every parity-dependent verb call
# was rejected downstream (observed end to end on the opbox door as
# `adapter_unauthorised`, with the agent honestly reporting it had no authorised
# tools). These pin the propagation AND its fail-closed scoping.


@pytest.mark.security
async def test_child_run_inherits_the_sealed_bearer(kernel):
    from boltrig.fleet.spawn import Spawner

    await kernel.credentials.seal_run_scoped_adapter_bearer(TENANT, RUN, "opbox", TOKEN)
    spawner = Spawner(kernel)
    child = "run-parity-child-1"
    await spawner._inherit_adapter_bearer(TENANT, RUN, child)

    cred = await kernel.credentials.resolve_run_scoped_credential(TENANT, child, "opbox")
    assert cred is not None, "the delegated child must carry the caller's clamped bearer"
    assert bearer_token(cred) == TOKEN
    # Propagation, not widening: the parent's own seal is untouched.
    assert bearer_token(
        await kernel.credentials.resolve_run_scoped_credential(TENANT, RUN, "opbox")
    ) == TOKEN


@pytest.mark.security
async def test_inheritance_is_a_noop_without_a_seal(kernel):
    """Non-passthrough tenants are execution-neutral: nothing sealed, nothing minted,
    so dispatch keeps the adapter's static credential exactly as before."""
    from boltrig.fleet.spawn import Spawner

    spawner = Spawner(kernel)
    await spawner._inherit_adapter_bearer(TENANT, "run-with-nothing-sealed", "run-child-2")
    assert (
        await kernel.credentials.resolve_run_scoped_credential(TENANT, "run-child-2", "opbox")
        is None
    )


@pytest.mark.security
async def test_inheritance_does_not_widen_to_other_runs_or_adapters(kernel):
    from boltrig.fleet.spawn import Spawner

    await kernel.credentials.seal_run_scoped_adapter_bearer(TENANT, RUN, "opbox", TOKEN)
    spawner = Spawner(kernel)
    child = "run-parity-child-3"
    await spawner._inherit_adapter_bearer(TENANT, RUN, child)

    # Only the named child gains it; an unrelated run still resolves to None.
    assert await kernel.credentials.resolve_run_scoped_credential(TENANT, "run-stranger", "opbox") is None
    # And it stays scoped to the ONE adapter it was sealed for.
    assert await kernel.credentials.resolve_run_scoped_credential(TENANT, child, "jira") is None


@pytest.mark.security
async def test_root_spawn_without_a_parent_run_is_a_noop(kernel):
    """A root turn has no parent run to inherit from; this must not raise."""
    from boltrig.fleet.spawn import Spawner

    spawner = Spawner(kernel)
    await spawner._inherit_adapter_bearer(TENANT, None, "run-child-4")
    assert (
        await kernel.credentials.resolve_run_scoped_credential(TENANT, "run-child-4", "opbox")
        is None
    )
