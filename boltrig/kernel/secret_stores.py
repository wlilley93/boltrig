"""Where secret MATERIAL comes from, as opposed to which credential applies.

Split out of kernel/credentials.py, which crossed the 400-line ceiling when the
capability doctrine merged in. Two different questions live in that file and
this is the smaller, older one: resolution decides WHICH credential a call gets
(own, then org, then the environment binding, fenced on scope), and a secret
store decides how the bytes behind a reference are fetched. Nothing here knows
about scopes, and nothing there knows about Vault or an env var.
"""

from __future__ import annotations

import os
from typing import Protocol

from boltrig.models import CredentialResolution


class SecretStore(Protocol):
    """Fetches secret material by reference. Implementations: Vault, cloud KMS,
    Docker secrets, env. None ever persist material in the app DB."""

    async def fetch(self, store: str, ref: str) -> dict: ...


class EnvSecretStore:
    """Reads secret material from environment variables.

    The credential reference is an env var name; its value is JSON (a dict of
    material) or, failing that, the raw string under key ``value``.
    """

    # Process-critical names an env REF must NEVER resolve: a control-plane
    # operator with integration-registration rights could otherwise point a
    # credential ref at, say, BOLTRIG_AUDIT_HMAC_KEY and have the MCP transport
    # post it as a bearer to a registered external server - privilege
    # escalation plus exfiltration, with the audit chain's key crossing too.
    # Integration material lives under its own names (e.g. JIRA_API_KEY).
    _PROCESS_CRITICAL = frozenset(
        {
            "DATABASE_URL",
            "REDIS_URL",
            "BOLTRIG_AUDIT_HMAC_KEY",
            "BOLTRIG_DEV_AUTH",
            "BOLTRIG_PRODUCTION",
        }
    )

    async def fetch(self, store: str, ref: str) -> dict:
        if ref in self._PROCESS_CRITICAL:
            raise CredentialResolution(
                f"env secret ref '{ref}' names process configuration, not "
                "integration material; refusing to hand it to an adapter"
            )
        raw = os.environ.get(ref)
        if raw is None:
            raise CredentialResolution(f"env secret '{ref}' not set")
        try:
            import json

            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {"value": parsed}
        except ValueError:
            return {"value": raw}
