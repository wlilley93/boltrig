"""Store protocol fragment for decision-0021 realtime call persistence."""

from __future__ import annotations

from typing import Protocol

from boltrig.models import RealtimeCallEvent, RealtimeCallSession
from .artifact_contract import ArtifactStoreContract
from .device_contract import DeviceStoreContract
from .integration_contract import IntegrationStoreContract


class RealtimeCallStoreContract(
    ArtifactStoreContract, IntegrationStoreContract, DeviceStoreContract, Protocol
):
    async def create_realtime_call(self, call: RealtimeCallSession) -> None: ...

    async def get_realtime_call(
        self, tenant_id: str, call_id: str
    ) -> RealtimeCallSession | None: ...

    async def list_realtime_calls(
        self,
        tenant_id: str,
        owner_id: str,
        limit: int = 50,
        conversation_id: str | None = None,
    ) -> list[RealtimeCallSession]: ...

    async def get_current_realtime_call(
        self,
        tenant_id: str,
        owner_id: str,
        conversation_id: str | None = None,
    ) -> RealtimeCallSession | None: ...

    async def update_realtime_call(self, call: RealtimeCallSession) -> None: ...

    async def claim_realtime_call_media(
        self,
        tenant_id: str,
        call_id: str,
        channel_ids: list[str],
        token_hash: str,
    ) -> RealtimeCallSession | None: ...

    async def append_realtime_call_event(self, event: RealtimeCallEvent) -> None: ...

    async def list_realtime_call_events(
        self, tenant_id: str, call_id: str, limit: int = 500
    ) -> list[RealtimeCallEvent]: ...

    async def get_realtime_call_hitl_event(
        self, tenant_id: str, call_id: str, request_id: str
    ) -> RealtimeCallEvent | None: ...

    async def summarize_realtime_call_usage(
        self, tenant_id: str, call_id: str
    ) -> dict[str, int | str | None]: ...
