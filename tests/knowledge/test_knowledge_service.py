from __future__ import annotations

import base64
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from boltrig.knowledge.adapter import KnowledgeAdapter
from boltrig.knowledge.filesystem_vault import FilesystemObjectVault
from boltrig.knowledge.memory_repository import InMemoryKnowledgeRepository
from boltrig.knowledge.models import MAX_UPLOAD_BYTES, Provider
from boltrig.knowledge.projections import (
    KnowledgeProjectionCoordinator,
    provider_defaults,
    retire_legacy_providers,
)
from boltrig.knowledge.service import KnowledgeService
from boltrig.memory.cognee import CogneeRuntimeModel
from boltrig.adapters.base import ErrorClass
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import GrantMissing, GrantSet, InvocationContext, TenantPermissions
from boltrig.store import InMemoryStore

TENANT = "knowledge-test"


class NoopProjections:
    async def compile(self, tenant_id, asset, segments, context):
        return []

    async def erase(self, tenant_id, asset_id, segment_ids, context=None):
        return []

    async def refresh_health(self, tenant_id, context=None):
        return None


def context(
    user: str, *, workspace: str | None = "workspace-a", extra: dict | None = None
) -> InvocationContext:
    return InvocationContext(
        tenant_id=TENANT,
        workspace_id=workspace,
        actor=user,
        actor_tier="human",
        grants=GrantSet.of(["knowledge.*"]),
        extra=dict(extra or {}),
    )


async def service(tmp_path: Path, *, projections=None):
    repository = InMemoryKnowledgeRepository()
    await repository.ensure_providers(TENANT, provider_defaults(TENANT))
    return KnowledgeService(
        repository,
        FilesystemObjectVault(tmp_path / "vault"),
        projections or NoopProjections(),
    )


async def ingest(svc: KnowledgeService, ctx: InvocationContext, text: str, title="Rig notes"):
    begun = await svc.begin_upload(
        {"title": title, "filename": "rig.md", "media_type": "text/markdown"}, ctx
    )
    await svc.stage_upload(begun["upload_id"], text.encode(), ctx)
    return await svc.commit_upload(begun["upload_id"], ctx)


async def test_asset_library_pages_without_truncating_the_accessible_set(
    tmp_path: Path,
) -> None:
    svc = await service(tmp_path)
    ctx = context("will")
    await ingest(svc, ctx, "first source", title="First")
    await ingest(svc, ctx, "second source", title="Second")

    first = await svc.list_assets({"limit": 1, "offset": 0}, ctx)
    second = await svc.list_assets({"limit": 1, "offset": first["next_offset"]}, ctx)

    assert len(first["assets"]) == len(second["assets"]) == 1
    assert first["assets"][0]["id"] != second["assets"][0]["id"]
    assert first["next_offset"] == 1
    assert second["next_offset"] is None


def pdf_bytes(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    document = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(document))
        document.extend(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = len(document)
    document.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        document.extend(f"{offset:010d} 00000 n \n".encode())
    document.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(document)


@pytest.mark.invariant("KNO-01")
async def test_original_revision_search_and_context_keep_stable_citations(tmp_path: Path) -> None:
    svc = await service(tmp_path)
    ctx = context("will")
    committed = await ingest(
        svc,
        ctx,
        "# Knowledge rig\n\nThe anchor shackle is rated to ninety kilograms.",
    )

    result = await svc.search({"query": "anchor shackle", "limit": 5}, ctx)
    hit = result["hits"][0]
    assert hit["citation"]["asset_id"] == committed["asset_id"]
    assert hit["citation"]["revision_id"] == committed["revision_id"]
    assert hit["citation"]["segment_id"].startswith("seg_")
    assert hit["citation"]["content_hash"]

    package = await svc.build_context({"query": "anchor shackle"}, ctx)
    assert package["items"][0]["trust"] == "untrusted_source_content"
    assert package["items"][0]["citation"] == hit["citation"]
    assert (
        package["context_hash"]
        == (await svc.build_context({"query": "anchor shackle"}, ctx))["context_hash"]
    )

    asset = await svc.get_asset(committed["asset_id"], ctx)
    assert asset["provenance"]["occurrences"][0]["external_path"] == "rig.md"
    assert asset["provenance"]["occurrences"][0]["source_kind"] == "upload"
    embedding = asset["provenance"]["embeddings"][0]
    assert embedding["subject_id"] == hit["citation"]["segment_id"]
    assert embedding["model_name"] == "HashingEmbedder"
    assert embedding["dimensions"] == 256
    assert "vector" not in embedding

    original = await svc.original(committed["asset_id"], ctx)
    assert base64.b64decode(original["data"]) == (
        b"# Knowledge rig\n\nThe anchor shackle is rated to ninety kilograms."
    )


@pytest.mark.invariant("KNO-01")
async def test_pdf_ingestion_returns_a_page_stable_citation(tmp_path: Path) -> None:
    svc = await service(tmp_path)
    ctx = context("will")
    data = pdf_bytes("Renewal notice is ninety days")
    begun = await svc.begin_upload(
        {"title": "Agreement", "filename": "agreement.pdf", "media_type": "application/pdf"},
        ctx,
    )
    await svc.stage_upload(begun["upload_id"], data, ctx)
    committed = await svc.commit_upload(begun["upload_id"], ctx)

    hit = (await svc.search({"query": "renewal notice"}, ctx))["hits"][0]
    assert hit["asset_id"] == committed["asset_id"]
    assert hit["citation"]["locator"]["page"] == 1
    assert base64.b64decode((await svc.original(committed["asset_id"], ctx))["data"]) == data


@pytest.mark.invariant("SEC-KNO-01")
async def test_retrieval_filters_access_before_returning_any_candidate(tmp_path: Path) -> None:
    svc = await service(tmp_path)
    owner = context("will", workspace=None)
    stranger = context("mallory", workspace=None)
    committed = await ingest(svc, owner, "Private acquisition codename albatross")

    assert (await svc.search({"query": "albatross"}, stranger))["hits"] == []
    with pytest.raises(LookupError, match="asset not found"):
        await svc.get_asset(committed["asset_id"], stranger)
    with pytest.raises(LookupError, match="asset not found"):
        await svc.original(committed["asset_id"], stranger)


@pytest.mark.invariant("KNO-02")
async def test_cognee_degradation_never_rolls_back_canonical_ingest(tmp_path: Path) -> None:
    repository = InMemoryKnowledgeRepository()
    await repository.ensure_providers(TENANT, provider_defaults(TENANT))
    coordinator = KnowledgeProjectionCoordinator(repository, {"cognee": {}})
    svc = KnowledgeService(repository, FilesystemObjectVault(tmp_path / "vault"), coordinator)
    ctx = context("will")

    committed = await ingest(svc, ctx, "Canonical source survives compiler failure")

    assert committed["status"] == "committed"
    assert committed["projections"][0]["provider_id"] == "cognee"
    assert committed["projections"][0]["status"] in {"written", "failed"}
    assert (await svc.search({"query": "compiler failure"}, ctx))["hits"]


@pytest.mark.invariant("KNO-03")
async def test_erasure_preserves_deduplicated_blob_until_last_reference(tmp_path: Path) -> None:
    svc = await service(tmp_path)
    ctx = context("will")
    first = await ingest(svc, ctx, "The same immutable bytes", title="First")
    second = await ingest(svc, ctx, "The same immutable bytes", title="Second")
    original = await svc.repository.original_for_asset(
        TENANT, second["asset_id"], ["user:will", "workspace:workspace-a"]
    )
    assert original is not None
    object_path = svc.vault._path(original[0])
    assert object_path.exists()

    erased_first = await svc.erase_asset(first["asset_id"], ctx)
    assert erased_first["objects_erased"] == 0
    assert object_path.exists()
    erased_second = await svc.erase_asset(second["asset_id"], ctx)
    assert erased_second["objects_erased"] == 1
    assert not object_path.exists()
    assert (await svc.search({"query": "immutable bytes"}, ctx))["hits"] == []


@pytest.mark.invariant("KNO-04")
async def test_cognee_is_the_only_shipped_knowledge_provider(
    tmp_path: Path,
) -> None:
    svc = await service(tmp_path)
    ctx = context("will")
    providers = {row["id"]: row for row in (await svc.list_providers(ctx))["providers"]}
    assert set(providers) == {"cognee"}
    assert providers["cognee"]["enabled"] is True
    assert providers["cognee"]["bundled"] is True

    with pytest.raises(LookupError, match="provider not found"):
        await svc.set_provider("supermemory", True, ctx)


@pytest.mark.invariant("KNO-05")
async def test_cognee_health_and_compile_use_the_callers_chat_route(
    tmp_path: Path,
) -> None:
    repository = InMemoryKnowledgeRepository()
    await repository.ensure_providers(TENANT, provider_defaults(TENANT))
    route = CogneeRuntimeModel(
        model_id="openai/gpt-5.4",
        endpoint="http://bifrost:8080/v1",
        api_key="gateway-secret",
        extra_headers=(("x-bf-vk", "vk-scoped"),),
    )

    class Resolver:
        def __init__(self) -> None:
            self.contexts = []

        async def resolve(self, tenant_id, invocation):
            assert tenant_id == TENANT
            self.contexts.append(invocation)
            return route

    resolver = Resolver()
    coordinator = KnowledgeProjectionCoordinator(
        repository,
        model_resolver=resolver,
    )
    coordinator._cognee.health = AsyncMock(return_value="ok")
    coordinator._cognee.remember = AsyncMock(return_value=["segment"])
    svc = KnowledgeService(
        repository,
        FilesystemObjectVault(tmp_path / "vault"),
        coordinator,
    )
    ctx = context("will")

    listed = await svc.list_providers(ctx)
    committed = await ingest(svc, ctx, "one governed source")
    await svc.set_provider("cognee", False, ctx)
    enabled = await svc.set_provider("cognee", True, ctx)

    assert listed["providers"][0]["health"] == "ok"
    assert committed["projections"][0]["status"] == "written"
    assert enabled["provider"]["health"] == "ok"
    assert resolver.contexts == [ctx, ctx, ctx]
    assert coordinator._cognee.remember.await_args.kwargs["runtime_model"] is route


@pytest.mark.invariant("KNO-04")
async def test_retired_provider_rows_are_disabled_and_hidden() -> None:
    assert [
        row.id
        for row in provider_defaults(
            TENANT,
            {"providers": [{"id": "mem0", "enabled": True}]},
        )
    ] == ["cognee"]

    repository = InMemoryKnowledgeRepository()
    await repository.ensure_providers(
        TENANT,
        [
            Provider(
                id="mem0",
                tenant_id=TENANT,
                display_name="Mem0",
                role="memory_compatibility",
                enabled=True,
                bundled=False,
                health="ok",
                status="enabled",
            )
        ],
    )
    await retire_legacy_providers(repository, TENANT)
    repaired = await repository.get_provider(TENANT, "mem0")
    assert repaired is not None
    assert repaired.enabled is False
    assert repaired.health == repaired.status == "retired"

    svc = KnowledgeService(repository, object(), NoopProjections())
    assert (await svc.list_providers(context("will")))["providers"] == []


@pytest.mark.invariant("KNO-01")
async def test_knowledge_adapter_runs_the_dispatch_chokepoint(tmp_path: Path) -> None:
    svc = await service(tmp_path)
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(TENANT, GrantSet.of(["knowledge.*"])))
    kernel = Kernel(store)
    await kernel.register_adapter(TENANT, KnowledgeAdapter(svc))
    ctx = context("will")

    output = await kernel.invoke(
        "knowledge",
        "knowledge.upload.begin",
        {"title": "Dispatch", "filename": "dispatch.txt", "media_type": "text/plain"},
        ctx,
    )
    assert output["upload_id"].startswith("upl_")
    audit = await store.audit_query(TENANT, limit=10)
    assert any(row.verb == "knowledge.upload.begin" and row.status == "ok" for row in audit)


@pytest.mark.invariant("KNO-01")
@pytest.mark.invariant("SEC-KNO-01")
async def test_mcp_resource_list_and_read_reuse_governed_asset_verbs(tmp_path: Path) -> None:
    svc = await service(tmp_path)
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(TENANT, GrantSet.of(["knowledge.*"])))
    kernel = Kernel(store)
    await kernel.register_adapter(TENANT, KnowledgeAdapter(svc))
    ctx = context("will")
    committed = await ingest(svc, ctx, "MCP resource bytes and citation")
    token = kernel.mcp.issue_run_token(
        TENANT,
        GrantSet.of(["knowledge.asset.list", "knowledge.asset.original"]),
        actor="will",
        workspace_id="workspace-a",
    )

    listed = await kernel.mcp.handle(token, {"jsonrpc": "2.0", "id": 1, "method": "resources/list"})
    resource = listed["result"]["resources"][0]
    assert resource["uri"].endswith(committed["asset_id"])
    read = await kernel.mcp.handle(
        token,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "resources/read",
            "params": {"uri": resource["uri"]},
        },
    )
    assert base64.b64decode(read["result"]["contents"][0]["blob"]) == (
        b"MCP resource bytes and citation"
    )
    audit = await store.audit_query(TENANT, limit=10)
    assert {row.verb for row in audit} >= {
        "knowledge.asset.list",
        "knowledge.asset.original",
    }


async def test_upload_size_cap_is_declared_and_enforced_before_vault_write(tmp_path: Path) -> None:
    svc = await service(tmp_path)
    ctx = context("will")
    begun = await svc.begin_upload(
        {"title": "Too big", "filename": "big.txt", "media_type": "text/plain"}, ctx
    )
    with pytest.raises(ValueError, match="exceeds"):
        await svc.stage_upload(begun["upload_id"], b"x" * (MAX_UPLOAD_BYTES + 1), ctx)


@pytest.mark.invariant("KNO-01")
def test_http_upload_and_search_are_thin_wrappers_over_governed_verbs(tmp_path: Path) -> None:
    async def build() -> Kernel:
        svc = await service(tmp_path)
        store = InMemoryStore()
        store.set_tenant_permissions(TenantPermissions(TENANT, GrantSet.of(["knowledge.*"])))
        kernel = Kernel(store)
        await kernel.register_adapter(TENANT, KnowledgeAdapter(svc))
        return kernel

    client = TestClient(create_app(asyncio.run(build())))
    headers = {
        "x-boltrig-tenant": TENANT,
        "x-boltrig-subject": "will",
        "x-boltrig-role": "org-admin",
        "x-boltrig-workspace": "workspace-a",
    }
    begin = client.post(
        "/v1/knowledge/uploads",
        json={"title": "HTTP source", "filename": "source.txt", "media_type": "text/plain"},
        headers=headers,
    )
    assert begin.status_code == 200
    upload_id = begin.json()["upload_id"]
    assert (
        client.put(
            f"/v1/knowledge/uploads/{upload_id}",
            content=b"HTTP citation survives the transport",
            headers=headers,
        ).status_code
        == 200
    )
    committed = client.post(f"/v1/knowledge/uploads/{upload_id}/commit", headers=headers)
    assert committed.status_code == 200
    found = client.post(
        "/v1/knowledge/search", json={"query": "citation transport"}, headers=headers
    )
    assert found.status_code == 200
    assert found.json()["hits"][0]["citation"]["asset_id"] == committed.json()["asset_id"]


@pytest.mark.invariant("SEC-KNO-01")
async def test_caller_supplied_extra_scopes_are_not_authority(tmp_path: Path) -> None:
    svc = await service(tmp_path)
    owner = context("will", workspace=None)
    committed = await ingest(svc, owner, "Private acquisition codename albatross")

    # A forged extra key claiming someone else's scopes must be ignored: the
    # service derives permitted scopes from the stamped principal fields only.
    forged = context("mallory", workspace=None, extra={"knowledge_scopes": ["user:will", "org"]})
    assert (await svc.search({"query": "albatross"}, forged))["hits"] == []
    with pytest.raises(LookupError, match="asset not found"):
        await svc.get_asset(committed["asset_id"], forged)
    with pytest.raises(PermissionError, match="not permitted"):
        await svc.begin_upload(
            {
                "title": "Forged",
                "filename": "f.txt",
                "media_type": "text/plain",
                "owner_scope": "user:will",
            },
            forged,
        )


@pytest.mark.invariant("SEC-KNO-01")
async def test_org_scope_is_limited_to_the_admin_tiers(tmp_path: Path) -> None:
    svc = await service(tmp_path)
    admin = context("admin-user", workspace=None, extra={"principal_role": "admin"})
    begun = await svc.begin_upload(
        {
            "title": "Org handbook",
            "filename": "org.md",
            "media_type": "text/markdown",
            "owner_scope": "org",
        },
        admin,
    )
    await svc.stage_upload(begun["upload_id"], b"Org-wide holiday policy", admin)
    committed = await svc.commit_upload(begun["upload_id"], admin)

    member = context("member-user", workspace=None, extra={"principal_role": "member"})
    with pytest.raises(PermissionError, match="not permitted"):
        await svc.begin_upload(
            {
                "title": "Forged org asset",
                "filename": "f.md",
                "media_type": "text/markdown",
                "owner_scope": "org",
            },
            member,
        )
    assert (await svc.search({"query": "holiday policy"}, member))["hits"] == []

    superadmin = context("other-admin", workspace=None, extra={"principal_role": "superadmin"})
    hits = (await svc.search({"query": "holiday policy"}, superadmin))["hits"]
    assert hits[0]["asset_id"] == committed["asset_id"]


@pytest.mark.invariant("KNO-01")
async def test_knowledge_verbs_are_grant_enforced_at_the_chokepoint(tmp_path: Path) -> None:
    svc = await service(tmp_path)
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(TENANT, GrantSet.of(["knowledge.*"])))
    kernel = Kernel(store)
    await kernel.register_adapter(TENANT, KnowledgeAdapter(svc))
    ungranted = InvocationContext(
        tenant_id=TENANT,
        workspace_id="workspace-a",
        actor="mallory",
        actor_tier="human",
        grants=GrantSet.of([]),
    )

    with pytest.raises(GrantMissing):
        await kernel.invoke(
            "knowledge",
            "knowledge.upload.begin",
            {"title": "Denied", "filename": "d.txt", "media_type": "text/plain"},
            ungranted,
        )
    audit = await store.audit_query(TENANT, limit=10)
    assert audit[-1].verb == "knowledge.upload.begin"
    assert audit[-1].status == "grant_missing"


async def test_concurrent_commits_get_one_winner_and_an_idempotent_replay(
    tmp_path: Path,
) -> None:
    svc = await service(tmp_path)
    ctx = context("will")
    begun = await svc.begin_upload(
        {"title": "Race", "filename": "race.txt", "media_type": "text/plain"}, ctx
    )
    await svc.stage_upload(begun["upload_id"], b"commit me exactly once", ctx)

    first, second = await asyncio.gather(
        svc.commit_upload(begun["upload_id"], ctx),
        svc.commit_upload(begun["upload_id"], ctx),
    )

    assert first["asset_id"] == second["asset_id"]
    assert sorted(bool(result.get("replayed")) for result in (first, second)) == [False, True]


async def test_internal_adapter_failure_is_redacted_to_the_type_name(tmp_path: Path) -> None:
    class BrokenService:
        async def begin_upload(self, params, context):
            raise RuntimeError("connect postgres://user:secret@db.internal:5432/knowledge")

    adapter = KnowledgeAdapter(BrokenService())
    result = await adapter.execute("knowledge.upload.begin", {}, None, context("will"))

    assert result.ok is False
    assert result.error.error_class == ErrorClass.INTERNAL
    assert result.error.message == "adapter error: RuntimeError"
    assert "db.internal" not in result.error.message


def test_provider_public_filters_sensitive_config_keys() -> None:
    provider = Provider(
        id="external-test",
        tenant_id=TENANT,
        display_name="External test",
        role="test_projection",
        enabled=False,
        bundled=False,
        config={
            "base_url": "https://projection.internal",
            "api_key": "k",
            "password": "p",
            "clientSecret": "s",
        },
    )

    assert provider.public()["config"] == {"base_url": "https://projection.internal"}


def _http_client(tmp_path: Path) -> TestClient:
    async def build() -> Kernel:
        svc = await service(tmp_path)
        store = InMemoryStore()
        store.set_tenant_permissions(TenantPermissions(TENANT, GrantSet.of(["knowledge.*"])))
        kernel = Kernel(store)
        await kernel.register_adapter(TENANT, KnowledgeAdapter(svc))
        return kernel

    return TestClient(create_app(asyncio.run(build())))


def _headers(subject: str, *, workspace: str, role: str = "org-admin", **extra: str) -> dict:
    return {
        "x-boltrig-tenant": TENANT,
        "x-boltrig-subject": subject,
        "x-boltrig-role": role,
        "x-boltrig-workspace": workspace,
        **extra,
    }


@pytest.mark.invariant("KNO-01")
@pytest.mark.invariant("SEC-KNO-01")
def test_http_denies_under_granted_and_cross_workspace_callers(tmp_path: Path) -> None:
    client = _http_client(tmp_path)
    owner = _headers("will", workspace="workspace-a")

    # Under-granted: an authenticated caller with no knowledge grants is
    # refused at the dispatcher before any service code runs.
    denied = client.post(
        "/v1/knowledge/uploads",
        json={"title": "Denied", "filename": "d.txt", "media_type": "text/plain"},
        headers=_headers("mallory", workspace="workspace-a", role="member"),
    )
    assert denied.status_code == 403

    # Cross-workspace: an asset ingested in workspace-a is invisible and
    # unreadable from workspace-b, even to an org-admin role.
    begin = client.post(
        "/v1/knowledge/uploads",
        json={"title": "Workspace A", "filename": "a.txt", "media_type": "text/plain"},
        headers=owner,
    )
    upload_id = begin.json()["upload_id"]
    client.put(f"/v1/knowledge/uploads/{upload_id}", content=b"workspace a secret", headers=owner)
    committed = client.post(f"/v1/knowledge/uploads/{upload_id}/commit", headers=owner)
    asset_id = committed.json()["asset_id"]

    stranger = _headers("mallory", workspace="workspace-b")
    assert client.get(f"/v1/knowledge/assets/{asset_id}", headers=stranger).status_code == 404
    listed = client.get("/v1/knowledge/assets", headers=stranger)
    assert listed.status_code == 200
    assert listed.json()["assets"] == []
    found = client.post("/v1/knowledge/search", json={"query": "secret"}, headers=stranger)
    assert found.status_code == 200
    assert found.json()["hits"] == []


def test_http_body_cap_exempts_only_the_knowledge_stage_route(tmp_path: Path) -> None:
    client = _http_client(tmp_path)
    headers = _headers("will", workspace="workspace-a")
    over_global_cap = b"x" * (1024 * 1024 + 1)  # > 1 MiB global cap, < 25 MiB route cap

    begin = client.post(
        "/v1/knowledge/uploads",
        json={"title": "Big", "filename": "big.txt", "media_type": "text/plain"},
        headers=headers,
    )
    upload_id = begin.json()["upload_id"]
    staged = client.put(
        f"/v1/knowledge/uploads/{upload_id}", content=over_global_cap, headers=headers
    )
    assert staged.status_code == 200

    refused = client.post(
        "/v1/knowledge/search",
        content=over_global_cap,
        headers={**headers, "content-type": "application/json"},
    )
    assert refused.status_code == 413
