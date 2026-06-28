"""Dispatch happy path, schema validation, fail-closed binding (US-KER-01, SEC-21)."""

import pytest

from nankle.models import BindingNotFound, SchemaValidationError
from tests.conftest import make_ctx


@pytest.mark.kernel
async def test_invoke_happy_path(kernel):
    out = await kernel.invoke(
        "ticket", "ticket.create", {"title": "Fix login"}, make_ctx(["ticket.create"])
    )
    assert out["title"] == "Fix login"
    assert out["status"] == "open"
    assert "id" in out


@pytest.mark.kernel
async def test_round_trip_create_then_read(kernel):
    created = await kernel.invoke(
        "ticket", "ticket.create", {"title": "T"}, make_ctx(["ticket.create"])
    )
    read = await kernel.invoke(
        "ticket", "ticket.read", {"id": created["id"]}, make_ctx(["ticket.read"])
    )
    assert read["id"] == created["id"]


@pytest.mark.kernel
@pytest.mark.invariant("SEC-21")
async def test_invalid_params_rejected_before_dispatch(kernel):
    with pytest.raises(SchemaValidationError):
        # missing required "title"
        await kernel.invoke("ticket", "ticket.create", {}, make_ctx(["ticket.create"]))


@pytest.mark.kernel
@pytest.mark.invariant("K-13")
async def test_unknown_verb_fails_closed(kernel):
    with pytest.raises(BindingNotFound):
        await kernel.invoke("ticket", "ticket.nope", {}, make_ctx(["ticket.nope"]))
