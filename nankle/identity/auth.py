"""Token verification and the principal resolver (US-IAM-01, SEC-01/02).

Identity is authenticated-by-construction (K-3): a verifier turns a bearer token
into verified claims, and a ``PrincipalResolver`` turns those claims into a
``Principal``. The tenant and subject come from the verified token, never from
the request body or an untrusted header, so a handler cannot be tricked into
acting as another tenant or user.

``authlib`` is imported lazily so this module (and the rest of the package) is
import-safe and offline-safe without it; OIDC verification raises a clear error
if it is missing. Production MUST use the real verifier (SEC-01/02); the
``dev_principal_resolver`` is a header-trusting convenience for local dev only.
"""

from __future__ import annotations

from typing import Any, Protocol

import httpx
from fastapi import HTTPException, Request

from nankle.kernel.app import Principal, PrincipalResolver
from nankle.models import RoleMapping

from .rbac import grants_for_scope, resolve_role


def _load_authlib_jwt() -> Any:
    """Lazy-import authlib's JWT codec, with a clear error if it is absent."""
    try:
        from authlib.jose import jwt
    except ImportError as exc:  # pragma: no cover - exercised only without authlib
        raise RuntimeError(
            "OIDC token verification requires the 'authlib' package "
            "(pip install authlib). SEC-01 mandates real token verification in "
            "production; only dev_principal_resolver may run without it."
        ) from exc
    return jwt


class Verifier(Protocol):
    """A bearer-token verifier seam: returns verified claims or raises."""

    async def verify(self, token: str) -> dict[str, Any]: ...


class OidcVerifier:
    """Verifies OIDC / OAuth2 JWT access tokens against an issuer's JWKS (SEC-01).

    Signature is checked against the issuer JWKS; ``iss``/``aud``/``exp``/``nbf``
    are validated. The JWKS is fetched once over httpx and cached.
    """

    def __init__(
        self,
        issuer: str,
        audience: str,
        jwks_uri: str,
        *,
        http_client: httpx.AsyncClient | None = None,
        leeway: int = 60,
    ) -> None:
        self.issuer = issuer
        self.audience = audience
        self.jwks_uri = jwks_uri
        self._http = http_client
        self._leeway = leeway
        self._jwks: dict[str, Any] | None = None

    async def _load_jwks(self) -> dict[str, Any]:
        if self._jwks is None:
            client = self._http or httpx.AsyncClient()
            try:
                resp = await client.get(self.jwks_uri)
                resp.raise_for_status()
                self._jwks = resp.json()
            finally:
                if self._http is None:
                    await client.aclose()
        return self._jwks

    async def verify(self, token: str) -> dict[str, Any]:
        """Verify ``token`` and return its claims, or raise on any failure."""
        jwt = _load_authlib_jwt()
        jwks = await self._load_jwks()
        claims_options = {
            "iss": {"essential": True, "value": self.issuer},
            "aud": {"essential": True, "value": self.audience},
        }
        claims = jwt.decode(token, jwks, claims_options=claims_options)
        claims.validate(leeway=self._leeway)  # exp / nbf / iss / aud
        return dict(claims)


class SamlVerifier:
    """SAML assertion verification seam (US-IAM-01).

    A placeholder for SAML-federated tenants: plug a concrete implementation
    (signature + audience + condition validation) via ``assertion_validator``.
    Kept as a seam so the OIDC path ships without a SAML stack.
    """

    def __init__(
        self,
        *,
        idp_metadata: str | None = None,
        audience: str | None = None,
        assertion_validator: Any | None = None,
    ) -> None:
        self.idp_metadata = idp_metadata
        self.audience = audience
        self._validator = assertion_validator

    async def verify(self, token: str) -> dict[str, Any]:
        if self._validator is None:
            raise NotImplementedError(
                "SAML verification is a seam; supply assertion_validator or use "
                "OidcVerifier. SEC-01 forbids unverified assertions in production."
            )
        return await self._validator(token)


def _bearer_token(request: Request) -> str:
    """Extract the bearer token from the Authorization header (SEC-02)."""
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="missing or malformed bearer token")
    return token.strip()


def _claim_groups(claims: dict[str, Any]) -> list[str]:
    """Pull IdP group membership out of common claim shapes."""
    for key in ("groups", "roles", "cognito:groups"):
        value = claims.get(key)
        if isinstance(value, list):
            return [str(g) for g in value]
        if isinstance(value, str) and value:
            return [value]
    return []


def _on_behalf_of(claims: dict[str, Any]) -> str | None:
    """Read the delegated-actor subject if the token is an OBO/act token (SEC-03)."""
    act = claims.get("act")
    if isinstance(act, dict) and act.get("sub"):
        return str(act["sub"])
    obo = claims.get("on_behalf_of")
    return str(obo) if obo else None


def build_principal_resolver(
    *,
    verifier: Verifier,
    mappings: list[RoleMapping],
    tenant_id: str,
) -> PrincipalResolver:
    """Build a production ``PrincipalResolver`` from a verifier (US-IAM-01/02).

    The returned resolver extracts the bearer, verifies it, derives the platform
    role + scope from the token's groups (US-IAM-02), and builds a ``Principal``
    whose grants are the scope's GrantSet ceiling. Tenant and subject come from
    the verified token / pinned tenant, never from the request body (SEC-02).
    """

    async def resolver(request: Request) -> Principal:
        token = _bearer_token(request)
        try:
            claims = await verifier.verify(token)
        except HTTPException:
            raise
        except Exception as exc:  # verification failure -> 401 (fail-closed)
            raise HTTPException(status_code=401, detail="token verification failed") from exc

        subject = claims.get("sub") or claims.get("subject")
        if not subject:
            raise HTTPException(status_code=401, detail="token has no subject claim")

        role, scope = resolve_role(_claim_groups(claims), mappings)
        return Principal(
            tenant_id=tenant_id,
            subject=str(subject),
            grants=grants_for_scope(scope),
            role=role,
            actor_tier="human",
            on_behalf_of=_on_behalf_of(claims),
            scope=scope,  # row-level department isolation in prod (US-IAM-02)
        )

    return resolver


async def dev_principal_resolver(request: Request) -> Principal:
    """Header-trusting resolver for LOCAL DEV ONLY (mirrors the kernel default).

    WARNING: trusts ``x-nankle-*`` headers with no verification. Production MUST
    use ``build_principal_resolver`` with a real verifier (SEC-01/02); never
    expose this resolver on a network-reachable deployment.
    """
    from nankle.models import GrantSet

    h = request.headers
    grants = [g for g in h.get("x-nankle-grants", "").split(",") if g]
    return Principal(
        tenant_id=h.get("x-nankle-tenant", "default"),
        subject=h.get("x-nankle-subject", "dev"),
        grants=GrantSet.of(grants),
        role=h.get("x-nankle-role", "org-admin"),
        actor_tier=h.get("x-nankle-tier", "human"),
        on_behalf_of=h.get("x-nankle-obo"),
    )
