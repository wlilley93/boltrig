"""Process settings from the environment (S11, deployment).

Process-level wiring (where the DB is, which secret store, the egress proxy)
comes from the environment; per-tenant policy comes from the fleet manifest.
These are kept apart so the same image runs many tenants. A small frozen
dataclass over ``os.environ`` keeps this import-safe with no settings framework.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

_TRUE = {"1", "true", "yes", "on", "y", "t"}


def _as_bool(value: str | None, default: bool = False) -> bool:
    """Parse an env-style boolean; missing / blank -> ``default``."""
    if value is None or value == "":
        return default
    return value.strip().lower() in _TRUE


@dataclass(frozen=True)
class Settings:
    """Immutable process settings (one per process, read once at boot)."""

    database_url: str | None = None
    redis_url: str | None = None
    secret_store: str = "env"  # 'env' | 'vault' | 'kms' | 'docker' ...
    audit_hmac_key: str | None = None  # BOLTRIG_AUDIT_HMAC_KEY (tamper-evident audit)
    https_proxy: str | None = None  # egress proxy for adapter HTTP calls
    ca_bundle: str | None = None  # custom CA bundle for TLS verification
    air_gapped: bool = False  # no outbound network allowed (SEC / local-only)
    # Identity (SEC-01). When the OIDC trio is set, real token verification is
    # used; dev_auth gates the header-trusting fallback for local dev only.
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_uri: str | None = None
    dev_auth: bool = False  # BOLTRIG_DEV_AUTH=1 -> header-trust resolver (dev only)

    @property
    def oidc_configured(self) -> bool:
        return bool(self.oidc_issuer and self.oidc_audience and self.oidc_jwks_uri)


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Build :class:`Settings` from ``env`` (defaults to ``os.environ``)."""
    e = env if env is not None else os.environ
    return Settings(
        database_url=e.get("DATABASE_URL") or None,
        redis_url=e.get("REDIS_URL") or None,
        secret_store=(e.get("SECRET_STORE") or "env").strip().lower(),
        audit_hmac_key=e.get("BOLTRIG_AUDIT_HMAC_KEY") or None,
        https_proxy=e.get("HTTPS_PROXY") or e.get("https_proxy") or None,
        ca_bundle=e.get("CA_BUNDLE") or None,
        air_gapped=_as_bool(e.get("AIR_GAPPED")),
        oidc_issuer=e.get("OIDC_ISSUER") or None,
        oidc_audience=e.get("OIDC_AUDIENCE") or None,
        oidc_jwks_uri=e.get("OIDC_JWKS_URI") or None,
        dev_auth=_as_bool(e.get("BOLTRIG_DEV_AUTH")),
    )
