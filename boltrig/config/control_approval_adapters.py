"""Integration and adapter approval fingerprints."""

from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import urlsplit

from boltrig.models import AdapterFailure, InvocationContext
from boltrig.store.mcp_lifecycle import mcp_credential_config_digest

from .control_rehydrate import consumer_spec, is_mcp_consumer, rehydratable
from .control_safety import ControlConflict

LIFECYCLE_ACTIONS = frozenset(
    {"control.adapter.deactivate", "control.adapter.delete"}
)
MCP_LIFECYCLE_ACTIONS = frozenset(
    {
        "control.mcp_server.probe",
        "control.mcp_server.activate",
        "control.mcp_server.deactivate",
        "control.mcp_server.retire",
        "control.mcp_server.restore",
        "control.mcp_server.update",
        "control.mcp_server.delete",
    }
)


def _mcp_spec_approval_view(record: Any) -> dict[str, Any]:
    spec = consumer_spec(getattr(record, "spec_ref", None))
    raw = str(spec.get("url") or "")
    try:
        parsed = urlsplit(raw)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        parsed = urlsplit("")
        hostname = None
        port = None
    origin = None
    if parsed.scheme.lower() in {"http", "https"} and hostname:
        shown_host = f"[{hostname}]" if ":" in hostname else hostname
        netloc = f"{shown_host}:{port}" if port is not None else shown_host
        origin = f"{parsed.scheme.lower()}://{netloc}"
    return {
        "endpoint_origin": origin,
        "path_redacted": bool((parsed.path or "").strip("/")) if origin else False,
        "allow_internal_egress": bool(spec.get("allow_internal")),
        "mcp_spec_digest": hashlib.sha256(
            str(getattr(record, "spec_ref", None) or "").encode("utf-8")
        ).hexdigest(),
    }


async def integration_context(
    store: Any, params: dict[str, Any], context: InvocationContext
) -> dict[str, Any]:
    connection = await store.get_integration_connection(
        context.tenant_id, str(params["connection_id"])
    )
    if connection is None:
        raise AdapterFailure(
            "integration connection not found",
            status_code=404,
            reason="control_resource_not_found",
        )
    return {
        "integration_connection": {
            "id": connection.id,
            "integration_id": connection.integration_id,
            "adapter_id": connection.adapter_id,
            "health": connection.health,
            "credential_ref": connection.credential_ref,
            "credential_owned": connection.credential_owned,
        }
    }


def _generated_approval_verbs(record: Any) -> list[dict[str, Any]]:
    from .control_generated_adapter import generated_adapter_from_record

    try:
        generated = generated_adapter_from_record(record)
    except ValueError as exc:
        raise AdapterFailure(
            "generated adapter reconstruction source is invalid",
            status_code=409,
            reason="control_adapter_unrehydratable",
        ) from exc
    return [
        {
            "id": item.verb_id,
            "input": item.input_schema,
            "output": item.output_schema,
            "consequence": item.consequence,
        }
        for item in generated.describe()
    ]


def _generated_source_digest(record: Any) -> str:
    encoded = str(record.spec_ref or "").encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


async def _store_adapter_view(
    store: Any, record: Any, context: InvocationContext
) -> dict[str, Any]:
    """Fingerprint a persisted adapter when no loader instance is available."""
    from .control_generated_adapter import is_generated_adapter_record

    verbs: list[dict[str, Any]] = []
    if is_generated_adapter_record(record):
        verbs = _generated_approval_verbs(record)
    else:
        for verb in await store.list_all_verbs(context.tenant_id):
            binding = await store.get_binding(context.tenant_id, verb.id)
            if binding is not None and binding.target_ref == record.id:
                verbs.append(
                    {
                        "id": verb.id,
                        "input": verb.input_schema,
                        "output": verb.output_schema,
                        "consequence": verb.consequence.value,
                    }
                )
    verbs.sort(key=lambda item: item["id"])
    view = {
        "adapter": {
            "id": record.id,
            "version": record.version,
            "runtime": record.runtime,
            "source": record.source,
            "activated": bool(record.activated),
            "verbs": verbs,
        }
    }
    # Bind the reviewed endpoint/SEC-61 waiver so approval cannot be replayed
    # after either changes.
    spec = consumer_spec(getattr(record, "spec_ref", None))
    if is_mcp_consumer(record) and (
        spec.get("url") is not None or spec.get("allow_internal")
    ):
        view["adapter"].update(_mcp_spec_approval_view(record))
    if is_generated_adapter_record(record):
        view["adapter"]["source_digest"] = _generated_source_digest(record)
    return view


async def _requested_mcp_config(
    store: Any,
    tenant_id: str,
    record: Any,
    lifecycle: Any,
    verb: str,
    params: dict[str, Any],
) -> dict[str, Any] | None:
    if verb != "control.mcp_server.update":
        return None
    from .control_mcp_mutations import prepare_mcp_amendment

    try:
        prepared = await prepare_mcp_amendment(
            store,
            tenant_id,
            record,
            params,
            current_config_revision=lifecycle.config_revision,
        )
    except ControlConflict as exc:
        raise AdapterFailure(
            "invalid MCP server replacement configuration",
            status_code=409,
            reason="control_conflict",
        ) from exc
    return prepared.requested_config


def _mcp_context_view(
    record: Any,
    lifecycle: Any,
    credential_ref: Any,
    published: Any,
    latest: Any,
    requested_config: dict[str, Any] | None,
) -> dict[str, Any]:
    from .control_mcp_lifecycle import snapshot_digest

    return {
        "id": record.id,
        "version": record.version,
        "state": lifecycle.state,
        "config_revision": lifecycle.config_revision,
        "lifecycle_created_at": lifecycle.created_at.isoformat(),
        "lifecycle_updated_at": lifecycle.updated_at.isoformat(),
        **_mcp_spec_approval_view(record),
        "credential_config_digest": mcp_credential_config_digest(credential_ref),
        "snapshot_digest": snapshot_digest(lifecycle.last_known_tools),
        "tools_observed_at": (
            lifecycle.tools_observed_at.isoformat()
            if lifecycle.tools_observed_at
            else None
        ),
        "published_digest": snapshot_digest(published),
        **(
            {"requested_config": requested_config}
            if requested_config is not None
            else {}
        ),
        "latest_probe": (
            None
            if latest is None
            else {
                "probe_id": latest.probe_id,
                "outcome": latest.outcome,
                "failure_code": latest.failure_code,
                "observed_at": latest.observed_at.isoformat(),
            }
        ),
    }


async def mcp_server_context(
    store: Any,
    verb: str,
    params: dict[str, Any],
    context: InvocationContext,
) -> dict[str, Any]:
    from .control_mcp_lifecycle import owned_tool_snapshot
    from .control_mcp_mutations import effective_mcp_credential_id

    server_id = str(params.get("server_id") or "")
    record = await store.get_adapter(context.tenant_id, server_id)
    lifecycle = await store.get_mcp_server_lifecycle(
        context.tenant_id, server_id
    )
    if (
        record is None
        or lifecycle is None
        or not is_mcp_consumer(record)
    ):
        raise AdapterFailure(
            "MCP server not found",
            status_code=404,
            reason="control_resource_not_found",
        )
    if (
        verb in {
            "control.mcp_server.probe",
            "control.mcp_server.activate",
        }
        and not rehydratable(record)
    ):
        raise AdapterFailure(
            "MCP server endpoint is not configured",
            status_code=409,
            reason="endpoint_not_configured",
        )
    _validate_mcp_context(verb, lifecycle)
    latest = await store.get_latest_mcp_probe_receipt(
        context.tenant_id, server_id
    )
    published = await owned_tool_snapshot(
        store, context.tenant_id, server_id
    )
    credential_id = await effective_mcp_credential_id(
        store, context.tenant_id, record
    )
    credential_ref = (
        await store.get_credential_ref(context.tenant_id, credential_id)
        if credential_id
        else None
    )
    requested_config = await _requested_mcp_config(
        store, context.tenant_id, record, lifecycle, verb, params
    )
    return {
        "mcp_server": _mcp_context_view(
            record,
            lifecycle,
            credential_ref,
            published,
            latest,
            requested_config,
        )
    }


def _validate_mcp_context(verb: str, lifecycle: Any) -> None:
    expected = {
        "control.mcp_server.activate": "inactive",
        "control.mcp_server.deactivate": "active",
        "control.mcp_server.retire": "inactive",
        "control.mcp_server.restore": "retired",
        "control.mcp_server.update": "inactive",
    }.get(verb)
    if expected is not None and lifecycle.state != expected:
        raise AdapterFailure(
            f"MCP server must be {expected}",
            status_code=409,
            reason="control_conflict",
        )
    if verb == "control.mcp_server.probe" and lifecycle.state == "retired":
        raise AdapterFailure(
            "retired MCP servers cannot be probed",
            status_code=409,
            reason="control_conflict",
        )
    if (
        verb == "control.mcp_server.delete"
        and lifecycle.state not in {"inactive", "retired"}
    ):
        raise AdapterFailure(
            "active MCP servers must be deactivated before deletion",
            status_code=409,
            reason="control_conflict",
        )
    if (
        verb == "control.mcp_server.activate"
        and lifecycle.tools_observed_at is None
    ):
        raise AdapterFailure(
            "MCP server must be probed before activation",
            status_code=409,
            reason="reprobe_required",
        )


async def adapter_context(
    store: Any,
    loader: Any,
    verb: str,
    params: dict[str, Any],
    context: InvocationContext,
) -> dict[str, Any]:
    if loader is None:
        raise AdapterFailure(
            "adapter loader not wired",
            status_code=503,
            reason="control_dependency_unavailable",
        )
    adapter = await loader.get(context.tenant_id, params["adapter_id"])
    if adapter is None:
        record = await store.get_adapter(context.tenant_id, params["adapter_id"])
        if record is None:
            raise AdapterFailure(
                "adapter not found",
                status_code=404,
                reason="control_resource_not_found",
            )
        if is_mcp_consumer(record):
            raise AdapterFailure(
                "external MCP servers use dedicated lifecycle controls",
                status_code=409,
                reason="control_conflict",
            )
        if verb in LIFECYCLE_ACTIONS or rehydratable(record):
            return await _store_adapter_view(store, record, context)
        raise AdapterFailure(
            "adapter cannot be reconstructed from its store row; "
            "delete and re-register it",
            status_code=409,
            reason="control_adapter_unrehydratable",
        )
    record = await store.get_adapter(context.tenant_id, params["adapter_id"])
    if record is not None and is_mcp_consumer(record):
        raise AdapterFailure(
            "external MCP servers use dedicated lifecycle controls",
            status_code=409,
            reason="control_conflict",
        )
    verbs = [
        {
            "id": item.verb_id,
            "input": item.input_schema,
            "output": item.output_schema,
            "consequence": item.consequence,
        }
        for item in adapter.describe()
    ]
    view = {
        "adapter": {
            "id": adapter.id,
            "version": adapter.version,
            "runtime": adapter.runtime,
            "source": getattr(adapter, "source", None),
            "activated": bool(record and record.activated),
            "verbs": verbs,
        }
    }
    if record is not None and rehydratable(record):
        from .control_generated_adapter import is_generated_adapter_record

        if is_generated_adapter_record(record):
            view["adapter"]["source_digest"] = _generated_source_digest(record)
        else:
            view["adapter"].update(_mcp_spec_approval_view(record))
    return view
