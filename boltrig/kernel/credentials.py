"""Credential resolution (P3, US-KER-03, SEC-04/05, K-20).

Credentials are resolved only inside the kernel, at call time, from an external
secret store. The application DB never holds plaintext: a credential_refs row is
either a pure *reference* (``{store, ref}`` into a SecretStore) or a reference
dict carrying inline material that the store seam envelope-SEALS at rest
(``boltrig/store/sealing.py``) and unseals transparently on read. A resolved
``Credential`` is handed to one adapter call and never returned to,
embedded in, or logged by an agent.
"""

from __future__ import annotations

import os
from typing import Protocol

from boltrig.adapters.base import Credential
from boltrig.models import CredentialResolution
from boltrig.store import Store


class SecretStore(Protocol):
    """Fetches secret material by reference. Implementations: Vault, cloud KMS,
    Docker secrets, env. None ever persist material in the app DB."""

    async def fetch(self, store: str, ref: str) -> dict: ...


class EnvSecretStore:
    """Reads secret material from environment variables.

    The credential reference is an env var name; its value is JSON (a dict of
    material) or, failing that, the raw string under key ``value``.
    """

    async def fetch(self, store: str, ref: str) -> dict:
        raw = os.environ.get(ref)
        if raw is None:
            raise CredentialResolution(f"env secret '{ref}' not set")
        try:
            import json

            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {"value": parsed}
        except ValueError:
            return {"value": raw}


class CredentialResolver:
    def __init__(self, store: Store, secret_store: SecretStore | None = None) -> None:
        self._store = store
        self._secret = secret_store or EnvSecretStore()
        # adapter id -> credential id, populated from the manifest at boot.
        self._adapter_cred: dict[tuple[str, str], str] = {}

    def bind_adapter_credential(self, tenant_id: str, adapter_id: str, cred_id: str) -> None:
        self._adapter_cred[(tenant_id, adapter_id)] = cred_id

    async def resolve_for_adapter(
        self, tenant_id: str, adapter_id: str
    ) -> Credential | None:
        """Resolve the credential an adapter needs, or ``None`` if it needs none."""
        cred_id = self._adapter_cred.get((tenant_id, adapter_id))
        if cred_id is None:
            return None  # adapter requires no credential (e.g. a local script)
        ref = await self._store.get_credential_ref(tenant_id, cred_id)
        if ref is None:
            raise CredentialResolution(
                f"no credential reference '{cred_id}' for tenant '{tenant_id}'"
            )
        material = await self.fetch_material(ref)
        return Credential(id=cred_id, kind=ref.get("kind", "api_key"), material=material)

    async def fetch_material(self, ref: dict) -> dict:
        """Fetch the material behind a stored credential REFERENCE ({store, ref})
        through the SecretStore seam. Kernel-side only (SEC-04/05): the material
        is never logged, audited, or handed to an agent."""
        return await self._secret.fetch(ref.get("store", "env"), ref["ref"])
