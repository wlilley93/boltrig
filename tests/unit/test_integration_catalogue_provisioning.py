from __future__ import annotations

import pytest

from boltrig.config.integration_catalogue import (
    certified_builtin_integrations,
    provision_builtin_integration_catalogue,
)
from boltrig.models.integrations import IntegrationCatalogueRecord
from boltrig.store import InMemoryStore


@pytest.mark.asyncio
@pytest.mark.invariant("SEC-WRK-06")
async def test_certified_builtin_catalogue_provisioning_is_deterministic_and_scoped() -> None:
    store = InMemoryStore()
    await store.upsert_integration_catalogue(
        IntegrationCatalogueRecord(
            id="github",
            tenant_id="acme",
            label="GitHub preview",
            category="work",
            transport="rest",
            auth=[],
            description="Presentation metadata; no reviewed adapter contract.",
        )
    )

    await provision_builtin_integration_catalogue(store, "acme")
    first = await store.list_integration_catalogue("acme")
    await provision_builtin_integration_catalogue(store, "acme")
    second = await store.list_integration_catalogue("acme")

    assert first == second
    assert {row.id for row in second} == {"github", "jira", "runpod", "xai-voice"}
    github = next(row for row in second if row.id == "github")
    assert github.certification == "uncertified"
    assert github.secret_contract is None
    assert await store.list_integration_catalogue("rival") == []


@pytest.mark.invariant("SEC-WRK-06")
def test_certified_builtin_contracts_are_closed_and_match_shipped_credentials() -> None:
    catalogue = {row.id: row for row in certified_builtin_integrations("acme")}

    assert set(catalogue) == {"jira", "runpod", "xai-voice"}
    assert all(row.certification == "certified" for row in catalogue.values())
    assert all(row.auth == ["manual_secret"] for row in catalogue.values())
    assert all(row.adapter_id == row.id for row in catalogue.values())

    jira = catalogue["jira"].secret_contract
    assert jira is not None
    assert jira.credential_kind == "basic"
    assert [field.name for field in jira.fields] == [
        "base_url",
        "username",
        "api_token",
    ]
    assert jira.fields[0].secret is False
    assert jira.account_id_field == "base_url"

    for provider_id in ("runpod", "xai-voice"):
        contract = catalogue[provider_id].secret_contract
        assert contract is not None
        assert contract.credential_kind == "api_key"
        assert [field.name for field in contract.fields] == ["api_key"]
