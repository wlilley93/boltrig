"""AdminConfig - the Admin Console service (Round Three, Epic ADM).

The manifest stays the source of truth (C1): the console edits the manifest dict
in memory, records every change as a versioned ``ConfigRevision`` (history +
rollback, NFR-REL-01), and can export a manifest equivalent to the current live
configuration that re-imports identically (round-trip fidelity, FR-ADM-02). It
never writes code (C2); only config data. RBAC + audit are applied by the route
layer (SEC-32).
"""

from __future__ import annotations

import uuid
from typing import Any

import yaml

from boltrig.models import ConfigRevision


class AdminConfig:
    def __init__(self, store, *, tenant_id: str, doc: dict[str, Any] | None = None,
                 path: str | None = None) -> None:
        self._store = store
        self._tenant = tenant_id
        if doc is not None:
            self._doc = dict(doc)
        elif path:
            with open(path, encoding="utf-8") as fh:
                self._doc = yaml.safe_load(fh) or {}
        else:
            self._doc = {}

    def section(self, name: str) -> Any:
        return self._doc.get(name)

    async def update_section(self, name: str, value: Any, actor: str) -> ConfigRevision:
        """Validate, apply, and version a manifest-section edit (FR-ADM-01)."""
        if value is None:
            raise ValueError(f"section '{name}' value may not be null")
        self._doc[name] = value
        rev = ConfigRevision(
            tenant_id=self._tenant, kind="manifest_section", ref=name,
            version=uuid.uuid4().hex[:8], payload={"section": name, "value": value},
            actor=actor,
        )
        return await self._store.add_config_revision(rev)

    async def history(self, name: str) -> list[ConfigRevision]:
        return await self._store.list_config_revisions(self._tenant, "manifest_section", name)

    async def rollback(self, name: str, rev_id: int, actor: str) -> Any:
        """Restore a prior revision's value, recording the rollback (FR-ADM-02)."""
        rev = await self._store.get_config_revision(self._tenant, rev_id)
        if rev is None or rev.ref != name:
            raise ValueError(f"no revision {rev_id} for section '{name}'")
        value = rev.payload.get("value")
        self._doc[name] = value
        restored = ConfigRevision(
            tenant_id=self._tenant, kind="manifest_section", ref=name,
            version=uuid.uuid4().hex[:8],
            payload={"section": name, "value": value, "rolled_back_to": rev_id},
            actor=actor, rolled_back=True,
        )
        await self._store.add_config_revision(restored)
        return value

    def export_dict(self) -> dict[str, Any]:
        """The current live configuration as a manifest dict (C1 round-trip)."""
        return dict(self._doc)

    def export_yaml(self) -> str:
        return yaml.safe_dump(self._doc, sort_keys=False)

    def credential_refs(self) -> list[dict[str, Any]]:
        """Surface adapter credential references (never values) for rotation view
        (US-ADM-03). Reads the manifest adapters' credential ids."""
        out: list[dict[str, Any]] = []
        for adapter in self._doc.get("adapters", []) or []:
            cred = adapter.get("credential")
            if cred:
                out.append({"adapter": adapter.get("id"), "credential": cred})
        return out
