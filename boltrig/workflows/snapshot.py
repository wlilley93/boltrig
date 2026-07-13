"""Immutable, tenant/workspace-bound workflow snapshots for durable execution."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from boltrig.models import WorkflowDefinition, WorkflowSource

_SCHEMA = 1
_BODY_FIELDS = frozenset(
    {
        "id",
        "tenant_id",
        "version",
        "source",
        "definition",
        "intent_tags",
        "origin_task",
        "workspace_id",
    }
)


class WorkflowSnapshotError(ValueError):
    """A queued workflow snapshot is malformed, altered, or out of scope."""


def _canonical(value: Any) -> bytes:
    try:
        text = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise WorkflowSnapshotError("workflow snapshot is not canonical JSON") from exc
    return text.encode("utf-8")


def build_workflow_snapshot(workflow: WorkflowDefinition) -> dict[str, Any]:
    """Freeze the exact approved definition into a self-verifying JSON document."""
    body = {
        "id": workflow.id,
        "tenant_id": workflow.tenant_id,
        "version": workflow.version,
        "source": workflow.source.value,
        "definition": workflow.definition,
        "intent_tags": workflow.intent_tags,
        "origin_task": workflow.origin_task,
        "workspace_id": workflow.workspace_id,
    }
    encoded = _canonical(body)
    # Round-trip makes the returned snapshot independent of later mutations to
    # the in-memory WorkflowDefinition/dict that was approved and queued.
    frozen = json.loads(encoded)
    return {
        "schema": _SCHEMA,
        "workflow": frozen,
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }


def workflow_snapshot_digest(workflow: WorkflowDefinition) -> str:
    """Return the content digest used by approval binding and queue snapshots."""
    return str(build_workflow_snapshot(workflow)["sha256"])


def _validate_body(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict) or set(body) != _BODY_FIELDS:
        raise WorkflowSnapshotError("workflow snapshot fields are malformed")
    required_strings = ("id", "tenant_id", "version", "source")
    if any(not isinstance(body.get(key), str) or not body[key] for key in required_strings):
        raise WorkflowSnapshotError("workflow snapshot identifiers are malformed")
    if not isinstance(body.get("definition"), dict):
        raise WorkflowSnapshotError("workflow snapshot definition is malformed")
    tags = body.get("intent_tags")
    if not isinstance(tags, list) or any(not isinstance(item, str) for item in tags):
        raise WorkflowSnapshotError("workflow snapshot intent tags are malformed")
    for key in ("origin_task", "workspace_id"):
        if body.get(key) is not None and not isinstance(body[key], str):
            raise WorkflowSnapshotError(f"workflow snapshot {key} is malformed")
    return body


def workflow_from_snapshot(
    snapshot: Any,
    *,
    tenant_id: str,
    workflow_id: str,
    workspace_id: str | None,
) -> WorkflowDefinition:
    """Verify and restore the exact queued definition, failing closed on drift."""
    if not isinstance(snapshot, dict) or set(snapshot) != {"schema", "workflow", "sha256"}:
        raise WorkflowSnapshotError("workflow snapshot envelope is malformed")
    if type(snapshot.get("schema")) is not int or snapshot["schema"] != _SCHEMA:
        raise WorkflowSnapshotError("workflow snapshot schema is unsupported")
    digest = snapshot.get("sha256")
    if not isinstance(digest, str):
        raise WorkflowSnapshotError("workflow snapshot digest is malformed")
    body = _validate_body(snapshot.get("workflow"))
    expected = hashlib.sha256(_canonical(body)).hexdigest()
    if not hmac.compare_digest(digest, expected):
        raise WorkflowSnapshotError("workflow snapshot digest mismatch")
    if body["tenant_id"] != tenant_id or body["id"] != workflow_id:
        raise WorkflowSnapshotError("workflow snapshot identity mismatch")
    scoped_workspace = body["workspace_id"]
    if scoped_workspace is not None and scoped_workspace != workspace_id:
        raise WorkflowSnapshotError("workflow snapshot is outside the active workspace")
    try:
        source = WorkflowSource(body["source"])
    except ValueError as exc:
        raise WorkflowSnapshotError("workflow snapshot source is malformed") from exc
    return WorkflowDefinition(
        id=body["id"],
        tenant_id=body["tenant_id"],
        version=body["version"],
        source=source,
        definition=body["definition"],
        intent_tags=body["intent_tags"],
        origin_task=body["origin_task"],
        workspace_id=scoped_workspace,
    )
