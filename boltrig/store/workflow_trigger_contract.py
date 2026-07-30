"""Store protocol for workflow event bindings and replay receipts."""

from __future__ import annotations

from typing import Protocol

from boltrig.models.workflow_triggers import (
    WorkflowTrigger,
    WorkflowTriggerDelivery,
)


class WorkflowTriggerStoreContract(Protocol):
    async def create_workflow_trigger(self, trigger: WorkflowTrigger) -> bool: ...

    async def get_workflow_trigger(
        self, tenant_id: str, trigger_id: str
    ) -> WorkflowTrigger | None: ...

    async def list_workflow_triggers(
        self, tenant_id: str, workflow_id: str
    ) -> list[WorkflowTrigger]: ...

    async def list_channel_workflow_triggers(
        self, tenant_id: str, channel_id: str, *, limit: int = 32
    ) -> list[WorkflowTrigger]: ...

    async def set_workflow_trigger_enabled(
        self, tenant_id: str, trigger_id: str, enabled: bool
    ) -> WorkflowTrigger | None: ...

    async def rotate_workflow_trigger_secret(
        self, tenant_id: str, trigger_id: str, secret_hash: str
    ) -> WorkflowTrigger | None: ...

    async def record_workflow_trigger_delivery(
        self, delivery: WorkflowTriggerDelivery
    ) -> tuple[WorkflowTriggerDelivery, bool]: ...

    async def get_workflow_trigger_delivery(
        self, tenant_id: str, trigger_id: str, source_event_digest: str
    ) -> WorkflowTriggerDelivery | None: ...

    async def list_workflow_trigger_deliveries(
        self, tenant_id: str, trigger_id: str, *, limit: int = 20
    ) -> list[WorkflowTriggerDelivery]: ...
