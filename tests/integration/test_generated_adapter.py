"""AI-generated adapter from an OpenAPI spec + the review gate (US-ADP-01, SEC-22)."""

import asyncio

import pytest

from nankle.adapters.generator import generate_adapter_from_spec
from nankle.models import InvocationContext

_SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Petstore", "version": "1.0.0"},
    "paths": {
        "/pets": {
            "get": {
                "operationId": "pet.list",
                "responses": {"200": {"description": "ok"}},
            },
            "post": {
                "operationId": "pet.create",
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {"name": {"type": "string"}},
                                "required": ["name"],
                            }
                        }
                    }
                },
                "responses": {"201": {"description": "created"}},
            },
        }
    },
}


@pytest.mark.invariant("US-ADP-01")
def test_generator_derives_verbs_from_openapi():
    gen = generate_adapter_from_spec(_SPEC, adapter_id="petstore")
    verb_ids = {v.verb_id for v in gen.describe()}
    assert {"pet.list", "pet.create"} <= verb_ids


@pytest.mark.invariant("SEC-22")
def test_generated_adapter_inert_until_reviewed():
    gen = generate_adapter_from_spec(_SPEC, adapter_id="petstore")
    assert gen.activated is False  # review gate closed by default

    # even a stray dispatch cannot reach the backend while inert (defence in depth)
    ctx = InvocationContext(tenant_id="acme")
    result = asyncio.run(gen.execute("pet.list", {}, None, ctx))
    assert result.ok is False

    gen.review_and_activate("alice@acme")
    assert gen.activated is True
