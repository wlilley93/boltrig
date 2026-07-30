"""In-memory external-MCP lifecycle parity implementation."""

from __future__ import annotations

from dataclasses import replace
import json

from boltrig.models import (
    AdapterHealth,
    MCP_MAX_RETURNED_PROBE_RECEIPTS,
    MCP_PROBE_RECEIPTS_PER_SERVER,
    McpProbeReceipt,
    McpServerLifecycle,
)

from .mcp_lifecycle_codec import (
    MCP_CONSUMER_MODULE,
    aware,
    copy_lifecycle,
    tools,
    validate_probe_snapshot,
    validate_snapshot,
    validate_transition,
)
from .mcp_lifecycle_contract import (
    McpCredentialAmendment,
    McpRegistrationDeleteResult,
    mcp_credential_config_digest,
    mcp_registration_spec_digest,
    validate_mcp_registration_cas,
)
from .mcp_registration_memory import (
    MemoryRegistrationExpectation,
    amend_registration,
)
from .sealing import unseal_ref


def _stored_credential_id(spec_ref: str | None) -> str | None:
    if not spec_ref:
        return None
    try:
        value = json.loads(spec_ref)
    except (TypeError, ValueError):
        return None
    if not isinstance(value, dict):
        return None
    credential_id = value.get("credential_id")
    return credential_id if isinstance(credential_id, str) and credential_id else None


def _replacement_credential_id(spec_ref: str) -> str | None:
    try:
        value = json.loads(spec_ref)
    except (TypeError, ValueError) as exc:
        raise ValueError("replacement MCP spec must be a JSON object") from exc
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("url"), str)
        or not value["url"].strip()
        or type(value.get("allow_internal")) is not bool
    ):
        raise ValueError(
            "replacement MCP spec must contain url and allow_internal"
        )
    credential_id = value.get("credential_id")
    if credential_id is not None and (
        not isinstance(credential_id, str) or not credential_id
    ):
        raise ValueError("replacement MCP spec credential id is invalid")
    return credential_id


class McpLifecycleStoreMem:
    def _init_mcp_lifecycle_state(self) -> None:
        self._mcp_lifecycles: dict[tuple[str, str], McpServerLifecycle] = {}
        self._mcp_probe_receipts: dict[tuple[str, str, str], McpProbeReceipt] = {}

    def _delete_mcp_lifecycle_state(self, tenant_id: str, server_id: str) -> None:
        self._mcp_lifecycles.pop((tenant_id, server_id), None)
        for key in [
            key
            for key in self._mcp_probe_receipts
            if key[:2] == (tenant_id, server_id)
        ]:
            self._mcp_probe_receipts.pop(key, None)

    def _require_mcp_adapter(self, tenant_id: str, server_id: str):
        adapter = self._adapters.get((tenant_id, server_id))
        if adapter is None:
            raise LookupError("MCP adapter not found")
        if adapter.module_ref != MCP_CONSUMER_MODULE:
            raise ValueError("adapter is not an external MCP consumer")
        return adapter

    async def get_mcp_server_lifecycle(self, tenant_id, server_id):
        adapter = self._adapters.get((tenant_id, server_id))
        if adapter is None or adapter.module_ref != MCP_CONSUMER_MODULE:
            return None
        row = self._mcp_lifecycles.get((tenant_id, server_id))
        return None if row is None else copy_lifecycle(row)

    async def list_mcp_server_lifecycles(self, tenant_id):
        rows = [
            copy_lifecycle(row)
            for (row_tenant, server_id), row in self._mcp_lifecycles.items()
            if row_tenant == tenant_id
            and (tenant_id, server_id) in self._adapters
            and self._adapters[(tenant_id, server_id)].module_ref
            == MCP_CONSUMER_MODULE
        ]
        return sorted(rows, key=lambda row: row.server_id)

    async def set_mcp_server_lifecycle(
        self,
        tenant_id,
        server_id,
        *,
        expected_state,
        expected_config_revision,
        new_state,
        changed_at,
        last_known_tools=None,
        tools_observed_at=None,
    ):
        aware(changed_at, "changed_at")
        payload = validate_snapshot(last_known_tools, tools_observed_at)
        adapter = self._require_mcp_adapter(tenant_id, server_id)
        key = (tenant_id, server_id)
        previous = self._mcp_lifecycles.get(key)
        if (
            previous is None and expected_config_revision is not None
        ) or (
            previous is not None
            and previous.config_revision != expected_config_revision
        ):
            return None
        if not validate_transition(
            existing_state=None if previous is None else previous.state,
            expected_state=expected_state,
            new_state=new_state,
        ):
            return None
        previous_tools_at = None if previous is None else previous.tools_observed_at
        fresh = payload is not None and (
            previous_tools_at is None or tools_observed_at > previous_tools_at
        )
        lifecycle = McpServerLifecycle(
            tenant_id=tenant_id,
            server_id=server_id,
            state=new_state,
            config_revision=1 if previous is None else previous.config_revision,
            last_known_tools=(
                tools(payload)
                if fresh and payload is not None
                else () if previous is None else previous.last_known_tools
            ),
            created_at=changed_at if previous is None else previous.created_at,
            updated_at=(
                changed_at
                if previous is None or previous.updated_at is None
                else max(previous.updated_at, changed_at)
            ),
            retired_at=changed_at if new_state == "retired" else None,
            tools_observed_at=tools_observed_at if fresh else previous_tools_at,
        )
        self._mcp_lifecycles[key] = lifecycle
        self._adapters[key] = replace(adapter, activated=new_state == "active")
        return copy_lifecycle(lifecycle)

    async def record_mcp_probe_receipt(
        self, probe, *, expected_config_revision, last_known_tools=None
    ):
        payload = validate_probe_snapshot(probe, last_known_tools)
        adapter = self._require_mcp_adapter(probe.tenant_id, probe.server_id)
        lifecycle_key = (probe.tenant_id, probe.server_id)
        lifecycle = self._mcp_lifecycles.get(lifecycle_key)
        if lifecycle is None:
            raise LookupError("MCP lifecycle not found")
        if (
            type(expected_config_revision) is not int
            or expected_config_revision < 1
        ):
            raise ValueError("expected MCP config revision is invalid")
        if lifecycle.config_revision != expected_config_revision:
            return None
        key = (probe.tenant_id, probe.server_id, probe.probe_id)
        previous = self._mcp_probe_receipts.get(key)
        if previous is not None:
            if previous != probe:
                raise ValueError("MCP probe id already records a different attempt")
            return replace(previous)
        self._mcp_probe_receipts[key] = replace(probe)
        if payload is not None and (
            lifecycle.tools_observed_at is None
            or probe.observed_at > lifecycle.tools_observed_at
        ):
            self._mcp_lifecycles[lifecycle_key] = replace(
                lifecycle,
                last_known_tools=tools(payload),
                tools_observed_at=probe.observed_at,
                updated_at=max(lifecycle.updated_at or probe.observed_at, probe.observed_at),
            )
        candidates = [
            row
            for (tenant, server, _), row in self._mcp_probe_receipts.items()
            if tenant == probe.tenant_id and server == probe.server_id
        ]
        latest = max(candidates, key=lambda row: (row.observed_at, row.probe_id))
        if latest.probe_id == probe.probe_id:
            self._adapters[lifecycle_key] = replace(
                adapter,
                health=AdapterHealth.OK
                if probe.outcome == "succeeded"
                else AdapterHealth.DOWN,
            )
        retained = sorted(
            candidates,
            key=lambda row: (row.observed_at, row.probe_id),
            reverse=True,
        )
        for expired in retained[MCP_PROBE_RECEIPTS_PER_SERVER:]:
            self._mcp_probe_receipts.pop(
                (expired.tenant_id, expired.server_id, expired.probe_id), None
            )
        return replace(probe)

    async def get_latest_mcp_probe_receipt(self, tenant_id, server_id):
        rows = await self.list_mcp_probe_receipts(tenant_id, server_id, limit=1)
        return rows[0] if rows else None

    async def list_mcp_probe_receipts(self, tenant_id, server_id, limit=20):
        adapter = self._adapters.get((tenant_id, server_id))
        if adapter is None or adapter.module_ref != MCP_CONSUMER_MODULE:
            return []
        bounded = max(1, min(int(limit), MCP_MAX_RETURNED_PROBE_RECEIPTS))
        rows = [
            replace(row)
            for (tenant, server, _), row in self._mcp_probe_receipts.items()
            if tenant == tenant_id and server == server_id
        ]
        rows.sort(key=lambda row: (row.observed_at, row.probe_id), reverse=True)
        return rows[:bounded]

    def _effective_mcp_credential_id(self, tenant_id, server_id, spec_ref):
        explicit = _stored_credential_id(spec_ref)
        if explicit is not None:
            return explicit
        derived = f"{server_id}-mcp-token"
        return derived if (tenant_id, derived) in self._creds else None

    def _validate_credential_amendment(
        self,
        tenant_id: str,
        *,
        previous_credential_id: str | None,
        replacement_spec_ref: str,
        amendment: McpCredentialAmendment,
    ) -> str | None:
        replacement_id = _replacement_credential_id(replacement_spec_ref)
        if amendment.mode == "preserve":
            if replacement_id != previous_credential_id:
                raise ValueError(
                    "preserved MCP credential id differs from the registration"
                )
            return previous_credential_id
        if amendment.mode == "remove":
            if replacement_id is not None:
                raise ValueError("removed MCP credential remains in replacement spec")
            return None
        if replacement_id != amendment.credential_id:
            raise ValueError(
                "replacement MCP credential id differs from replacement spec"
            )
        assert amendment.credential_id is not None
        assert amendment.credential_metadata is not None
        existing = self._creds.get((tenant_id, amendment.credential_id))
        if (
            existing is not None
            and unseal_ref(existing) != dict(amendment.credential_metadata)
        ):
            raise ValueError(
                "existing MCP credential reference metadata is immutable"
            )
        return amendment.credential_id

    async def amend_mcp_server_registration(
        self,
        tenant_id,
        server_id,
        *,
        expected_state,
        expected_created_at,
        expected_updated_at,
        expected_spec_digest,
        expected_credential_config_digest,
        expected_config_revision,
        spec_ref,
        changed_at,
        credential_amendment,
    ):
        validate_mcp_registration_cas(
            expected_created_at=expected_created_at,
            expected_updated_at=expected_updated_at,
            expected_spec_digest=expected_spec_digest,
            expected_credential_config_digest=(
                expected_credential_config_digest
            ),
            expected_config_revision=expected_config_revision,
            changed_at=changed_at,
        )
        if expected_state != "inactive":
            raise ValueError("MCP amendment requires expected inactive state")
        if not isinstance(credential_amendment, McpCredentialAmendment):
            raise TypeError("credential_amendment must be McpCredentialAmendment")
        expected = MemoryRegistrationExpectation(
            expected_state,
            expected_created_at,
            expected_updated_at,
            expected_spec_digest,
            expected_credential_config_digest,
            expected_config_revision,
            changed_at,
        )
        return await amend_registration(
            self,
            tenant_id,
            server_id,
            expected,
            spec_ref,
            credential_amendment,
        )

    async def delete_mcp_server_registration(
        self,
        tenant_id,
        server_id,
        *,
        expected_state,
        expected_created_at,
        expected_updated_at,
        expected_spec_digest,
        expected_credential_config_digest,
        expected_config_revision,
        changed_at,
    ):
        validate_mcp_registration_cas(
            expected_created_at=expected_created_at,
            expected_updated_at=expected_updated_at,
            expected_spec_digest=expected_spec_digest,
            expected_credential_config_digest=(
                expected_credential_config_digest
            ),
            expected_config_revision=expected_config_revision,
            changed_at=changed_at,
        )
        if expected_state not in {"inactive", "retired"}:
            raise ValueError("MCP deletion requires inactive or retired state")
        adapter = self._require_mcp_adapter(tenant_id, server_id)
        lifecycle_row = self._mcp_lifecycles.get((tenant_id, server_id))
        if lifecycle_row is None:
            raise LookupError("MCP lifecycle not found")
        if (
            lifecycle_row.state != expected_state
            or lifecycle_row.created_at != expected_created_at
            or lifecycle_row.updated_at != expected_updated_at
            or lifecycle_row.config_revision != expected_config_revision
            or mcp_registration_spec_digest(adapter.spec_ref)
            != expected_spec_digest
        ):
            return None
        previous_credential_id = self._effective_mcp_credential_id(
            tenant_id, server_id, adapter.spec_ref
        )
        previous_credential = (
            None
            if previous_credential_id is None
            else self._creds.get((tenant_id, previous_credential_id))
        )
        actual_credential_digest = mcp_credential_config_digest(
            None
            if previous_credential is None
            else unseal_ref(previous_credential)
        )
        if actual_credential_digest != expected_credential_config_digest:
            return None
        self._adapters.pop((tenant_id, server_id), None)
        self._delete_mcp_lifecycle_state(tenant_id, server_id)
        return McpRegistrationDeleteResult(
            server_id,
            lifecycle_row.state,
            lifecycle_row.config_revision,
            changed_at,
        )


__all__ = ["McpLifecycleStoreMem"]
