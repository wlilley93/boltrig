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
# Every run-scoped seal names the user whose authority it carries, and only
# that identity can resolve it (see credentials._owner_matches).
OWNER = "alice@example.com"


@pytest.mark.security
async def test_sealed_bearer_resolves_for_same_run_and_adapter(kernel):
    await kernel.credentials.seal_run_scoped_adapter_bearer(TENANT, RUN, "opbox", TOKEN, OWNER)
    cred = await kernel.credentials.resolve_run_scoped_credential(TENANT, RUN, "opbox", OWNER)
    assert cred is not None
    # The dispatch override hands this to the adapter, which derives the bearer.
    assert bearer_token(cred) == TOKEN


@pytest.mark.security
async def test_scoped_fail_closed_to_run_and_adapter(kernel):
    await kernel.credentials.seal_run_scoped_adapter_bearer(TENANT, RUN, "opbox", TOKEN, OWNER)
    # A different run must not see it (another turn cannot borrow the bearer).
    assert await kernel.credentials.resolve_run_scoped_credential(TENANT, "run-other", "opbox", OWNER) is None
    # A different adapter must not see it (the bearer never leaks past its adapter).
    assert await kernel.credentials.resolve_run_scoped_credential(TENANT, RUN, "jira", OWNER) is None
    # A missing run id resolves to None (=> static credential fallback at dispatch).
    assert await kernel.credentials.resolve_run_scoped_credential(TENANT, None, "opbox", OWNER) is None


@pytest.mark.security
async def test_unsealed_resolves_none_static_fallback(kernel):
    # Nothing sealed => None, so _execute_adapter keeps the static service credential.
    assert await kernel.credentials.resolve_run_scoped_credential(TENANT, RUN, "opbox", OWNER) is None


@pytest.mark.security
@pytest.mark.invariant("K-20")
async def test_bearer_never_surfaced_through_param_resolver(kernel):
    """The adapter bearer shares the ``run:`` keyspace with secure answers, so a
    crafted ``credential:run/<run>/adapter_bearer:opbox`` reference in a verb
    param would resolve to the SAME sealed row. The distinct kind marker makes
    the param resolver fail closed instead of substituting the bearer - the only
    thing that keeps an agent from coaxing the bearer into an output."""
    await kernel.credentials.seal_run_scoped_adapter_bearer(TENANT, RUN, "opbox", TOKEN, OWNER)
    crafted = f"credential:run/{RUN}/adapter_bearer:opbox"
    with pytest.raises(CredentialResolution):
        await kernel.credentials.resolve_run_scoped_params(
            TENANT, {"leak": crafted}, run_id=RUN, owner=OWNER
        )


@pytest.mark.security
async def test_swept_with_the_run(kernel):
    await kernel.credentials.seal_run_scoped_adapter_bearer(TENANT, RUN, "opbox", TOKEN, OWNER)
    # Confirm it is sealed under the run keyspace, then the run-terminal sweep drops it.
    assert await kernel.store.get_credential_ref(TENANT, adapter_bearer_cred_id(RUN, "opbox")) is not None
    await kernel.credentials.sweep_run_scoped(TENANT, RUN)
    assert await kernel.credentials.resolve_run_scoped_credential(TENANT, RUN, "opbox", OWNER) is None


# --- delegation: the seal must survive a spawn ------------------------------
# A chat turn seals against the ROOT run but never calls verbs itself: it spawns an
# ephemeral worker and the dispatch happens under the CHILD's run id, which
# resolve_run_scoped_credential is keyed by. Without propagation the child silently
# fell back to the adapter's static credential and every parity-dependent verb call
# was rejected downstream (observed end to end on the opbox door as
# `adapter_unauthorised`, with the agent honestly reporting it had no authorised
# tools). These pin the propagation AND its fail-closed scoping.


@pytest.mark.security
@pytest.mark.usefixtures("opbox_addon")
async def test_child_run_inherits_the_sealed_bearer(kernel):
    from boltrig.fleet.spawn import Spawner

    await kernel.credentials.seal_run_scoped_adapter_bearer(TENANT, RUN, "opbox", TOKEN, OWNER)
    spawner = Spawner(kernel)
    child = "run-parity-child-1"
    await spawner._inherit_adapter_bearer(TENANT, RUN, child, OWNER)

    cred = await kernel.credentials.resolve_run_scoped_credential(TENANT, child, "opbox", OWNER)
    assert cred is not None, "the delegated child must carry the caller's clamped bearer"
    assert bearer_token(cred) == TOKEN
    # Propagation, not widening: the parent's own seal is untouched.
    assert bearer_token(
        await kernel.credentials.resolve_run_scoped_credential(TENANT, RUN, "opbox", OWNER)
    ) == TOKEN


@pytest.mark.security
async def test_inheritance_is_a_noop_without_a_seal(kernel):
    """Non-passthrough tenants are execution-neutral: nothing sealed, nothing minted,
    so dispatch keeps the adapter's static credential exactly as before."""
    from boltrig.fleet.spawn import Spawner

    spawner = Spawner(kernel)
    await spawner._inherit_adapter_bearer(TENANT, "run-with-nothing-sealed", "run-child-2", OWNER)
    assert (
        await kernel.credentials.resolve_run_scoped_credential(TENANT, "run-child-2", "opbox", OWNER)
        is None
    )


@pytest.mark.security
async def test_inheritance_does_not_widen_to_other_runs_or_adapters(kernel):
    from boltrig.fleet.spawn import Spawner

    await kernel.credentials.seal_run_scoped_adapter_bearer(TENANT, RUN, "opbox", TOKEN, OWNER)
    spawner = Spawner(kernel)
    child = "run-parity-child-3"
    await spawner._inherit_adapter_bearer(TENANT, RUN, child, OWNER)

    # Only the named child gains it; an unrelated run still resolves to None.
    assert await kernel.credentials.resolve_run_scoped_credential(TENANT, "run-stranger", "opbox", OWNER) is None
    # And it stays scoped to the ONE adapter it was sealed for.
    assert await kernel.credentials.resolve_run_scoped_credential(TENANT, child, "jira", OWNER) is None


@pytest.mark.security
async def test_root_spawn_without_a_parent_run_is_a_noop(kernel):
    """A root turn has no parent run to inherit from; this must not raise."""
    from boltrig.fleet.spawn import Spawner

    spawner = Spawner(kernel)
    await spawner._inherit_adapter_bearer(TENANT, None, "run-child-4", OWNER)
    assert (
        await kernel.credentials.resolve_run_scoped_credential(TENANT, "run-child-4", "opbox", OWNER)
        is None
    )


# --- the run id is not the whole fence --------------------------------------
# The run id was the ONLY thing gating these seals, on the assumption that a run
# id is server-minted. It is not: the write doors take it from the request body,
# so a bystander who quoted a stranger's run id was handed that stranger's sealed
# material - the reference's run id and the context run id it was checked against
# both came from the same request and so always agreed. These pin the second,
# independent fence at the resolver.


@pytest.mark.security
@pytest.mark.invariant("SEC-186")
async def test_a_bystander_quoting_the_run_id_cannot_borrow_the_bearer(kernel):
    await kernel.credentials.seal_run_scoped_adapter_bearer(TENANT, RUN, "opbox", TOKEN, OWNER)
    stolen = await kernel.credentials.resolve_run_scoped_credential(
        TENANT, RUN, "opbox", "mallory@example.com"
    )
    assert stolen is None, "another user's clamped downstream bearer was handed over"
    # Fail closed, not fail open: no identity at all resolves nothing either.
    assert await kernel.credentials.resolve_run_scoped_credential(TENANT, RUN, "opbox", None) is None


@pytest.mark.security
@pytest.mark.invariant("SEC-186")
async def test_a_bystander_quoting_the_run_id_cannot_read_a_secure_answer(kernel):
    reference = await kernel.credentials.seal_run_scoped_value(
        TENANT, RUN, "password", "hunter2", OWNER
    )
    with pytest.raises(CredentialResolution):
        await kernel.credentials.resolve_run_scoped_params(
            TENANT, {"secret": reference}, run_id=RUN, owner="mallory@example.com"
        )
    # The rightful owner is unaffected.
    resolved = await kernel.credentials.resolve_run_scoped_params(
        TENANT, {"secret": reference}, run_id=RUN, owner=OWNER
    )
    assert resolved == {"secret": "hunter2"}


@pytest.mark.security
@pytest.mark.invariant("SEC-186")
async def test_a_child_run_cannot_launder_a_strangers_bearer(kernel):
    """``POST /v1/spawn`` takes parent_run_id from the body, so without the owner
    fence a caller could name a victim's run as their parent and have the victim's
    bearer re-sealed onto a child run they own outright."""
    from boltrig.fleet.spawn import Spawner

    await kernel.credentials.seal_run_scoped_adapter_bearer(TENANT, RUN, "opbox", TOKEN, OWNER)
    spawner = Spawner(kernel)
    child = "run-mallorys-child"
    await spawner._inherit_adapter_bearer(TENANT, RUN, child, "mallory@example.com")
    assert (
        await kernel.credentials.resolve_run_scoped_credential(
            TENANT, child, "opbox", "mallory@example.com"
        )
        is None
    ), "a stranger's bearer was laundered into a run the caller owns"


@pytest.mark.security
@pytest.mark.invariant("SEC-186")
async def test_an_unowned_seal_is_refused_at_the_door(kernel):
    """Sealing without an owner would recreate the hole, so it is not possible."""
    with pytest.raises(CredentialResolution):
        await kernel.credentials.seal_run_scoped_adapter_bearer(TENANT, RUN, "opbox", TOKEN, "")
    with pytest.raises(CredentialResolution):
        await kernel.credentials.seal_run_scoped_value(TENANT, RUN, "password", "hunter2", "")
