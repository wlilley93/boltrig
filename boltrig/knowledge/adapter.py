"""Governed knowledge.* verbs exposed to Codex through the normal registry/MCP."""

from __future__ import annotations

import base64
import binascii
from typing import Any

from boltrig.adapters.base import (
    AdapterError,
    Credential,
    ErrorClass,
    McpResourceSpec,
    Result,
    VerbSpec,
)
from boltrig.models import InvocationContext

from .models import MAX_UPLOAD_BYTES

_OBJECT = {"type": "object"}
_ID = {"type": "string", "minLength": 1, "maxLength": 200}


class KnowledgeAdapter:
    id = "knowledge"
    version = "1.0.0"
    runtime = "script"
    source = "builtin"

    def __init__(self, service) -> None:
        self.service = service

    def describe(self) -> list[VerbSpec]:
        return [*_upload_specs(), *_retrieval_specs(), *_provider_specs()]

    def mcp_resources(self) -> list[McpResourceSpec]:
        return [
            McpResourceSpec(
                uri_prefix="boltrig://knowledge/assets/",
                list_verb="knowledge.asset.list",
                read_verb="knowledge.asset.original",
                collection_key="assets",
                read_id_param="asset_id",
            )
        ]

    async def execute(
        self,
        verb: str,
        params: dict[str, Any],
        credential: Credential | None,
        context: InvocationContext,
    ) -> Result:
        try:
            output = await self._execute(verb, params, context)
            return Result.success(output)
        except PermissionError as exc:
            return _failure(ErrorClass.UNAUTHORISED, exc)
        except LookupError as exc:
            return _failure(ErrorClass.NOT_FOUND, exc)
        except (ValueError, binascii.Error) as exc:
            return _failure(ErrorClass.INVALID, exc)
        except Exception as exc:  # a bad adapter must never crash the kernel (US-ADP-06)
            # Type name only: raw backend messages (boto3/asyncpg) can embed
            # endpoint URLs, bucket names, or DSN fragments.
            return Result.failure(
                AdapterError(ErrorClass.INTERNAL, f"adapter error: {type(exc).__name__}")
            )

    async def _execute(self, verb: str, params: dict[str, Any], context) -> dict[str, Any]:
        if verb == "knowledge.upload.begin":
            return await self.service.begin_upload(params, context)
        if verb == "knowledge.upload.stage":
            encoded = str(params.get("data") or "")
            data = base64.b64decode(encoded, validate=True)
            return await self.service.stage_upload(str(params["upload_id"]), data, context)
        if verb == "knowledge.upload.commit":
            return await self.service.commit_upload(str(params["upload_id"]), context)
        if verb == "knowledge.asset.list":
            return await self.service.list_assets(params, context)
        if verb == "knowledge.asset.get":
            return await self.service.get_asset(str(params["asset_id"]), context)
        if verb == "knowledge.asset.original":
            return await self.service.original(str(params["asset_id"]), context)
        if verb == "knowledge.search":
            return await self.service.search(params, context)
        if verb == "knowledge.context.build":
            return await self.service.build_context(params, context)
        if verb == "knowledge.asset.erase":
            return await self.service.erase_asset(str(params["asset_id"]), context)
        if verb == "knowledge.providers.list":
            return await self.service.list_providers(context)
        if verb == "knowledge.provider.enable":
            return await self.service.set_provider(str(params["provider_id"]), True, context)
        if verb == "knowledge.provider.disable":
            return await self.service.set_provider(str(params["provider_id"]), False, context)
        raise ValueError(f"unknown Knowledge verb {verb!r}")

    async def health(self) -> str:
        return "ok"


def _upload_specs() -> list[VerbSpec]:
    return [
            _verb(
                "knowledge.upload.begin",
                {
                    "title": {"type": "string", "minLength": 1, "maxLength": 500},
                    "filename": {"type": "string", "minLength": 1, "maxLength": 240},
                    "media_type": {"type": "string", "maxLength": 200},
                    "owner_scope": {"type": "string", "maxLength": 300},
                    "source_kind": {"type": "string", "maxLength": 100},
                    "source_ref": {"type": "string", "maxLength": 2000},
                },
                ["title", "filename", "media_type"],
                "Begin a bounded immutable-source upload",
            ),
            _verb(
                "knowledge.upload.stage",
                {
                    "upload_id": _ID,
                    "data": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": ((MAX_UPLOAD_BYTES + 2) // 3) * 4,
                    },
                },
                ["upload_id", "data"],
                "Stage base64 bytes with a digest and hard size cap",
            ),
            _verb(
                "knowledge.upload.commit",
                {"upload_id": _ID},
                ["upload_id"],
                "Commit an immutable revision, representation, segments, and citations",
            ),
    ]


def _retrieval_specs() -> list[VerbSpec]:
    return [
            _verb("knowledge.asset.list", {"limit": {"type": "integer", "minimum": 1}}, [],
                  "List accessible Knowledge assets"),
            _verb("knowledge.asset.get", {"asset_id": _ID}, ["asset_id"],
                  "Read an accessible asset and its stable segments"),
            _verb("knowledge.asset.original", {"asset_id": _ID}, ["asset_id"],
                  "Read the immutable original bytes with its media type"),
            _verb(
                "knowledge.search",
                {
                    "query": {"type": "string", "maxLength": 2000},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                },
                [],
                "Permission-first exact, lexical, and vector retrieval with citations",
            ),
            _verb(
                "knowledge.context.build",
                {
                    "query": {"type": "string", "minLength": 1, "maxLength": 2000},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                ["query"],
                "Build a typed, bounded, cited context package for Codex",
            ),
            _verb(
                "knowledge.asset.erase",
                {"asset_id": _ID},
                ["asset_id"],
                "Erase an asset, unreferenced bytes, and derived projections",
                consequence="high",
            ),
    ]


def _provider_specs() -> list[VerbSpec]:
    return [
            _verb("knowledge.providers.list", {}, [],
                  "List canonical and add-on Knowledge provider state"),
            _verb(
                "knowledge.provider.enable",
                {"provider_id": _ID},
                ["provider_id"],
                "Enable a governed rebuildable provider",
                consequence="high",
            ),
            _verb(
                "knowledge.provider.disable",
                {"provider_id": _ID},
                ["provider_id"],
                "Disable a provider without changing canonical Knowledge",
                consequence="high",
            ),
        ]


def _verb(
    verb_id: str,
    properties: dict[str, Any],
    required: list[str],
    description: str,
    *,
    consequence: str = "low",
) -> VerbSpec:
    return VerbSpec(
        verb_id=verb_id,
        noun_id="knowledge",
        input_schema={
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
        output_schema=_OBJECT,
        consequence=consequence,
        description=description,
        rate_limit={"per": "minute", "max": 120, "scope": "verb"},
    )


def _failure(error_class: ErrorClass, exc: BaseException) -> Result:
    return Result.failure(
        AdapterError(error_class, f"{type(exc).__name__}: {exc}"[:500])
    )
