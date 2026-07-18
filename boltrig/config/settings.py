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
    # Codex read-only ledger scaffold (BOLTRIG_CODEX_LEDGER). Disabled by default;
    # when off the Codex execution stack is never constructed (a total no-op). When
    # on it is constructed and parked on app.state.platform, but nothing calls it
    # yet: wiring an admit() into the live path is a later, court-gated PR.
    codex_ledger: bool = False  # BOLTRIG_CODEX_LEDGER=1 -> construct the inert stack
    # Trusted single-tenant read-only Codex runtime ([2026] VJS-CC-VJS 2). Opt-in:
    # BOLTRIG_CODEX_TRUSTED=1 selects the loopback-proxy Codex runtime that mints a
    # per-cell bearer from the child's real process identity WITHOUT SO_PEERCRED, for
    # a single trusted operator only. Lawful ONLY when hard-walled from production
    # (see require_codex_trusted_posture): it requires dev_auth AND refuses under any
    # production signal or real ingress posture. Off by default = never constructed.
    codex_trusted: bool = False  # BOLTRIG_CODEX_TRUSTED=1 -> trusted Codex runtime
    # Cloudflare Access (zero-trust edge IdP). When the team domain + AUD are set,
    # the kernel verifies the per-request Cf-Access-Jwt-Assertion against CF's
    # JWKS and derives the principal from the authenticated email. Login, MFA and
    # SSO happen at the CF edge; the kernel trusts only the verified assertion.
    cf_access_team_domain: str | None = None  # https://<team>.cloudflareaccess.com
    cf_access_aud: str | None = None  # the Access application AUD tag
    cf_access_role_map: str | None = None  # JSON {email: role}
    cf_access_default_role: str = "none"  # role for an authed-but-unmapped email
    cf_access_tenant: str | None = None  # tenant the Access users belong to
    # First-party invite-only login ([2026] VJS-COUNTY 7). Opt-in: BOLTRIG_AUTH_MODE
    # =session selects the session principal resolver in place of Cloudflare Access,
    # so an existing deploy (mode unset) is unchanged. The console is single-tenant;
    # session_tenant is the tenant its users belong to. session_cookie_secure lets a
    # LOCAL http dev box drop the Secure flag - it defaults ON so prod is safe.
    auth_mode: str | None = None  # 'session' | None
    session_tenant: str | None = None
    session_cookie_secure: bool = True

    @property
    def oidc_configured(self) -> bool:
        return bool(self.oidc_issuer and self.oidc_audience and self.oidc_jwks_uri)

    @property
    def cf_access_configured(self) -> bool:
        return bool(self.cf_access_team_domain and self.cf_access_aud)

    @property
    def session_auth_configured(self) -> bool:
        return (self.auth_mode or "").strip().lower() == "session"


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
        codex_ledger=_as_bool(e.get("BOLTRIG_CODEX_LEDGER")),
        codex_trusted=_as_bool(e.get("BOLTRIG_CODEX_TRUSTED")),
        cf_access_team_domain=(e.get("CF_ACCESS_TEAM_DOMAIN") or "").rstrip("/") or None,
        cf_access_aud=e.get("CF_ACCESS_AUD") or None,
        cf_access_role_map=e.get("CF_ACCESS_ROLE_MAP") or None,
        cf_access_default_role=(e.get("CF_ACCESS_DEFAULT_ROLE") or "none").strip(),
        cf_access_tenant=e.get("CF_ACCESS_TENANT") or None,
        auth_mode=(e.get("BOLTRIG_AUTH_MODE") or "").strip().lower() or None,
        session_tenant=e.get("BOLTRIG_SESSION_TENANT") or None,
        session_cookie_secure=_as_bool(e.get("BOLTRIG_SESSION_COOKIE_SECURE"), default=True),
    )
