"""Thin HTTP transport for governed Knowledge verbs."""

from __future__ import annotations

import base64
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from boltrig.knowledge.models import MAX_UPLOAD_BYTES


def _context(principal):
    # The service derives permitted scopes server-side from the stamped
    # principal fields (rbac.knowledge_scopes); the transport passes no scope
    # claims of its own.
    return principal.context()


async def _invoke(kernel, principal, verb: str, params: dict) -> dict:
    return await kernel.invoke("knowledge", verb, params, _context(principal))


async def _bounded_body(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    if declared and int(declared) > MAX_UPLOAD_BYTES:
        raise ValueError(f"upload exceeds {MAX_UPLOAD_BYTES} bytes")
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_UPLOAD_BYTES:
            raise ValueError(f"upload exceeds {MAX_UPLOAD_BYTES} bytes")
    return bytes(data)


def register(app, P, K) -> None:
    @app.post("/v1/knowledge/uploads")
    async def begin_upload(body: dict, k=K, p=P) -> dict:
        return await _invoke(k, p, "knowledge.upload.begin", body)

    @app.put("/v1/knowledge/uploads/{upload_id}")
    async def stage_upload(upload_id: str, request: Request, k=K, p=P):
        try:
            data = await _bounded_body(request)
        except (ValueError, TypeError):
            return JSONResponse(
                {"status": "error", "reason": f"upload exceeds {MAX_UPLOAD_BYTES} bytes"},
                status_code=413,
            )
        return await _invoke(
            k,
            p,
            "knowledge.upload.stage",
            {"upload_id": upload_id, "data": base64.b64encode(data).decode("ascii")},
        )

    @app.post("/v1/knowledge/uploads/{upload_id}/commit")
    async def commit_upload(upload_id: str, k=K, p=P) -> dict:
        return await _invoke(k, p, "knowledge.upload.commit", {"upload_id": upload_id})

    @app.get("/v1/knowledge/assets")
    async def list_assets(limit: int = 50, k=K, p=P) -> dict:
        return await _invoke(k, p, "knowledge.asset.list", {"limit": limit})

    @app.get("/v1/knowledge/assets/{asset_id}")
    async def get_asset(asset_id: str, k=K, p=P) -> dict:
        return await _invoke(k, p, "knowledge.asset.get", {"asset_id": asset_id})

    @app.get("/v1/knowledge/assets/{asset_id}/original")
    async def original(asset_id: str, k=K, p=P) -> Response:
        output = await _invoke(k, p, "knowledge.asset.original", {"asset_id": asset_id})
        filename = str(output["filename"])
        headers = {"content-disposition": f"attachment; filename*=UTF-8''{quote(filename)}"}
        return Response(
            base64.b64decode(output["data"], validate=True),
            media_type=str(output["media_type"]),
            headers=headers,
        )

    @app.post("/v1/knowledge/search")
    async def search(body: dict, k=K, p=P) -> dict:
        return await _invoke(k, p, "knowledge.search", body)

    @app.post("/v1/knowledge/context")
    async def context(body: dict, k=K, p=P) -> dict:
        return await _invoke(k, p, "knowledge.context.build", body)

    @app.delete("/v1/knowledge/assets/{asset_id}")
    async def erase(asset_id: str, k=K, p=P) -> dict:
        return await _invoke(k, p, "knowledge.asset.erase", {"asset_id": asset_id})

    @app.get("/v1/knowledge/providers")
    async def providers(k=K, p=P) -> dict:
        return await _invoke(k, p, "knowledge.providers.list", {})

    @app.post("/v1/knowledge/providers/{provider_id}")
    async def set_provider(provider_id: str, body: dict, k=K, p=P) -> dict:
        verb = "knowledge.provider.enable" if body.get("enabled") else "knowledge.provider.disable"
        return await _invoke(k, p, verb, {"provider_id": provider_id})
