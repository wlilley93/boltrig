"""Persist bounded, structured artifacts declared by an agent result.

The internal runtime result is still untrusted data. The only accepted envelope
is ``output.artifacts = [{name, media_type, data, previous_revision_id?}]``,
where ``data`` is strict base64. Server context owns every authority field.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import uuid
from dataclasses import dataclass
from typing import Any

from boltrig.models.artifacts import MAX_ARTIFACT_BYTES, Artifact, ArtifactProvenance

MAX_RESULT_ARTIFACTS = 10


@dataclass(frozen=True)
class ArtifactProduction:
    declared: int
    recorded: tuple[Artifact, ...]
    rejected: int


@dataclass(frozen=True)
class ArtifactContext:
    tenant_id: str
    owner_id: str
    workspace_id: str | None
    conversation_id: str | None
    run_id: str
    work_item_id: str
    actor_ref: str


def _actor_ref(result: dict[str, Any]) -> str:
    value = result.get("agent_type")
    if (
        isinstance(value, str)
        and value
        and len(value.encode("utf-8")) <= 256
        and all(character.isprintable() for character in value)
    ):
        return value
    return "agent"


def _declarations(result: dict[str, Any]) -> tuple[list[Any], int, int]:
    output = result.get("output")
    if not isinstance(output, dict) or "artifacts" not in output:
        return [], 0, 0
    declarations = output["artifacts"]
    if not isinstance(declarations, list):
        return [], 1, 1
    overflow = max(0, len(declarations) - MAX_RESULT_ARTIFACTS)
    return declarations[:MAX_RESULT_ARTIFACTS], len(declarations), overflow


def _decode_declaration(
    declaration: Any,
) -> tuple[str, str, bytes, str | None]:
    if not isinstance(declaration, dict):
        raise ValueError("artifact declaration must be an object")
    name = declaration.get("name")
    media_type = declaration.get("media_type")
    encoded = declaration.get("data")
    if not all(isinstance(value, str) for value in (name, media_type, encoded)):
        raise ValueError("artifact fields must be strings")
    previous_id = declaration.get("previous_revision_id")
    if previous_id is not None and not isinstance(previous_id, str):
        raise ValueError("previous revision id must be a string")
    return name, media_type, base64.b64decode(encoded, validate=True), previous_id


async def _revision(
    store: Any,
    context: ArtifactContext,
    *,
    name: str,
    previous_id: str | None,
) -> int:
    if previous_id is None:
        return 1
    previous = await store.get_artifact_scoped(
        context.tenant_id,
        previous_id,
        context.owner_id,
        workspace_id=context.workspace_id,
    )
    if (
        previous is None
        or previous.conversation_id != context.conversation_id
        or previous.name != name
    ):
        raise ValueError("previous artifact revision is unavailable")
    return previous.revision + 1


def _artifact(
    context: ArtifactContext,
    *,
    index: int,
    name: str,
    media_type: str,
    content: bytes,
    previous_id: str | None,
    revision: int,
) -> Artifact:
    digest = hashlib.sha256(content).hexdigest()
    identity = "\0".join(
        (
            "boltrig-result-artifact",
            context.tenant_id,
            context.owner_id,
            context.conversation_id or "",
            context.run_id,
            str(index),
            digest,
        )
    )
    return Artifact(
        id=uuid.uuid5(uuid.NAMESPACE_URL, identity).hex,
        tenant_id=context.tenant_id,
        owner_id=context.owner_id,
        workspace_id=context.workspace_id,
        conversation_id=context.conversation_id,
        run_id=context.run_id,
        work_item_id=context.work_item_id,
        name=name,
        digest=digest,
        media_type=media_type,
        size=len(content),
        revision=revision,
        previous_revision_id=previous_id,
        provenance=ArtifactProvenance(
            kind="agent",
            actor_ref=context.actor_ref,
            source_ref=context.run_id,
        ),
    )


async def _persist(
    store: Any, context: ArtifactContext, artifact: Artifact, content: bytes
) -> Artifact:
    if await store.record_artifact(artifact, content):
        return artifact
    existing = await store.get_artifact_scoped(
        context.tenant_id,
        artifact.id,
        context.owner_id,
        workspace_id=context.workspace_id,
    )
    if existing is None or existing.digest != artifact.digest:
        raise ValueError("artifact record was refused")
    return existing


async def record_result_artifacts(
    store: Any,
    result: dict[str, Any],
    *,
    tenant_id: str,
    owner_id: str,
    workspace_id: str | None,
    conversation_id: str | None,
    run_id: str,
    work_item_id: str,
) -> ArtifactProduction:
    """Record valid declarations; count invalid or failed records without leaking."""

    declarations, declared, rejected = _declarations(result)
    context = ArtifactContext(
        tenant_id,
        owner_id,
        workspace_id,
        conversation_id,
        run_id,
        work_item_id,
        _actor_ref(result),
    )
    recorded: list[Artifact] = []
    total_bytes = 0
    for index, declaration in enumerate(declarations):
        try:
            name, media_type, content, previous_id = _decode_declaration(declaration)
            total_bytes += len(content)
            if total_bytes > MAX_ARTIFACT_BYTES:
                raise ValueError("result artifact total is too large")
            revision = await _revision(
                store, context, name=name, previous_id=previous_id
            )
            candidate = _artifact(
                context,
                index=index,
                name=name,
                media_type=media_type,
                content=content,
                previous_id=previous_id,
                revision=revision,
            )
            recorded.append(await _persist(store, context, candidate, content))
        except (binascii.Error, TypeError, ValueError):
            rejected += 1
        except Exception:
            rejected += 1
    return ArtifactProduction(declared, tuple(recorded), rejected)


def _publish(relay: Any, stream_id: str, production: ArtifactProduction) -> None:
    for artifact in production.recorded:
        relay.publish(
            stream_id,
            {
                "type": "artifact",
                "artifact_id": artifact.id,
                "name": artifact.name,
                "media_type": artifact.media_type,
                "size": artifact.size,
            },
        )
    if production.rejected:
        relay.publish(
            stream_id,
            {"type": "artifact_rejected", "count": production.rejected},
        )


async def produce_spawn_artifacts(
    kernel: Any,
    result: Any,
    *,
    capability_name: str,
    context: Any,
    run_id: str,
) -> ArtifactProduction:
    """Canonical runtime-to-artifact seam for every governed fleet spawn."""

    conversation = context.extra.get("conversation_id")
    conversation_id = conversation if isinstance(conversation, str) else None
    envelope = {"agent_type": capability_name, "output": result.output}
    production = await record_result_artifacts(
        kernel.store,
        envelope,
        tenant_id=context.tenant_id,
        owner_id=context.on_behalf_of or context.actor,
        workspace_id=context.workspace_id,
        conversation_id=conversation_id,
        run_id=run_id,
        work_item_id=context.run_id or run_id,
    )
    if context.run_id:
        _publish(
            kernel.events.for_tenant(context.tenant_id),
            context.run_id,
            production,
        )
    return production


def spawn_result_envelope(
    *,
    run_id: str,
    capability_name: str,
    result: Any,
    cost_micros: int,
    effective_grants: Any,
    artifacts: ArtifactProduction,
    spawn_rule: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the public spawn result without returning artifact bytes."""

    envelope = {
        "run_id": run_id,
        "agent_type": capability_name,
        "status": "ok" if result.ok else "error",
        "degraded": bool(result.degraded or artifacts.rejected),
        "summary": result.summary,
        "output": result.output,
        "tokens_used": result.tokens_used,
        "cost_micros": cost_micros,
        "new_work_items": list(result.new_work_items),
        "effective_grants": list(effective_grants),
        "artifacts": [
            {"id": artifact.id, "name": artifact.name}
            for artifact in artifacts.recorded
        ],
        "artifact_rejected": artifacts.rejected,
    }
    if spawn_rule is not None:
        envelope["spawn_rule"] = spawn_rule
    return envelope


__all__ = [
    "MAX_RESULT_ARTIFACTS",
    "ArtifactProduction",
    "produce_spawn_artifacts",
    "record_result_artifacts",
    "spawn_result_envelope",
]
