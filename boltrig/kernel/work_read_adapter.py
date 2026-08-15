"""Kernel-native, scoped agent access to Boltrig's canonical Work board."""

from __future__ import annotations

from typing import Any

from boltrig.adapters.base import AdapterError, ErrorClass, Result, VerbSpec
from boltrig.identity.rbac import departments_for
from boltrig.models import InvocationContext, WorkItem, WorkStatus
from boltrig.store.work_mutations import work_item_visible

_ITEM_OUTPUT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "intent": {"type": "string"},
        "status": {"type": "string"},
        "confidence": {"type": "number"},
        "convergent": {"type": "boolean"},
        "owner_member": {"type": ["string", "null"]},
        "source": {"type": "string"},
        "parent_id": {"type": ["string", "null"]},
        "depth": {"type": "integer"},
        "workspace_id": {"type": ["string", "null"]},
    },
    "required": ["id", "intent", "status", "confidence", "convergent", "source", "depth"],
    "additionalProperties": False,
}


def _view(item: WorkItem) -> dict[str, Any]:
    """Project only planning state; raw source payloads and run results stay private."""
    return {
        "id": item.id,
        "intent": item.intent,
        "status": item.status.value,
        "confidence": item.confidence,
        "convergent": item.convergent,
        "owner_member": item.owner_member,
        "source": item.source,
        "parent_id": item.parent_id,
        "depth": item.depth,
        "workspace_id": item.workspace_id,
    }


def _departments(context: InvocationContext) -> list[str] | None:
    extra = context.extra or {}
    return departments_for(
        str(extra.get("principal_role") or ""),
        extra.get("principal_scope") if isinstance(extra.get("principal_scope"), dict) else None,
    )


class WorkReadAdapter:
    """List and read canonical work without granting authoring authority."""

    id = "work-board"
    version = "1.0.0"
    runtime = "script"

    def __init__(self, store: Any) -> None:
        self._store = store

    def describe(self) -> list[VerbSpec]:
        status = {"type": "string", "enum": [value.value for value in WorkStatus]}
        return [
            VerbSpec(
                verb_id="work.list",
                noun_id="work",
                input_schema={
                    "type": "object",
                    "properties": {
                        "status": status,
                        "parent_id": {"type": "string", "minLength": 1, "maxLength": 200},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                        "cursor": {"type": "string", "minLength": 1, "maxLength": 200},
                    },
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "items": {"type": "array", "items": _ITEM_OUTPUT, "maxItems": 100},
                        "next_cursor": {"type": ["string", "null"]},
                    },
                    "required": ["items", "next_cursor"],
                    "additionalProperties": False,
                },
                description=(
                    "List canonical Work items visible in the active workspace. "
                    "Use this before creating duplicate work or changing an item by id."
                ),
            ),
            VerbSpec(
                verb_id="work.get",
                noun_id="work",
                input_schema={
                    "type": "object",
                    "properties": {"item_id": {"type": "string", "minLength": 1, "maxLength": 200}},
                    "required": ["item_id"],
                    "additionalProperties": False,
                },
                output_schema={
                    "type": "object",
                    "properties": {"item": _ITEM_OUTPUT},
                    "required": ["item"],
                    "additionalProperties": False,
                },
                description=(
                    "Read one canonical Work item by an exact id returned from work.list. "
                    "Raw source payloads and execution results are not exposed."
                ),
            ),
        ]

    async def execute(
        self,
        verb: str,
        params: dict[str, Any],
        credential: Any,
        context: InvocationContext,
    ) -> Result:
        departments = _departments(context)
        if verb == "work.get":
            item = await self._store.get_work_item(
                context.tenant_id,
                str(params["item_id"]),
                workspace_id=context.workspace_id,
                enforce_workspace=True,
            )
            if not work_item_visible(item, context.workspace_id, departments):
                return Result.failure(AdapterError(ErrorClass.NOT_FOUND, "work item not found"))
            return Result.success({"item": _view(item)})
        if verb == "work.list":
            status = WorkStatus(str(params["status"])) if params.get("status") else None
            limit = int(params.get("limit", 50))
            items = await self._store.list_work_items(
                context.tenant_id,
                status,
                params.get("parent_id"),
                departments,
                limit,
                params.get("cursor"),
                workspace_id=context.workspace_id,
                enforce_workspace=True,
            )
            return Result.success(
                {
                    "items": [_view(item) for item in items],
                    "next_cursor": items[-1].id if len(items) == limit else None,
                }
            )
        return Result.failure(AdapterError(ErrorClass.NOT_FOUND, "unknown work read verb"))

    async def health(self) -> str:
        return "ok"


def build_work_read_adapter(store: Any) -> WorkReadAdapter:
    return WorkReadAdapter(store)
