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

import base64
import json
import time
from typing import Any, Protocol

import httpx
from fastapi import HTTPException, Request

from boltrig.kernel.app import Principal, PrincipalResolver
from boltrig.models import RoleMapping

from .rbac import DEFAULT_ROLE, grants_for_scope, resolve_role


def _load_authlib_jwt(algorithms: list[str] | None = None) -> Any:
    """Lazy-import authlib's JWT codec, with a clear error if it is absent.

    When ``algorithms`` is given, return a ``JsonWebToken`` PINNED to exactly that
    allowlist (IAM-02) - authlib then rejects any token whose ``alg`` is not in it
    (incl. ``none`` and HS* confusion). Without it, the module default is returned.
    """
    try:
        if algorithms is not None:
            from authlib.jose import JsonWebToken

            return JsonWebToken(list(algorithms))
        from authlib.jose import jwt
    except ImportError as exc:  # pragma: no cover - exercised only without authlib
        raise RuntimeError(
            "OIDC token verification requires the 'authlib' package "
            "(pip install authlib). SEC-01 mandates real token verification in "
            "production; only dev_principal_resolver may run without it."
        ) from exc
    return jwt


def _b64url(segment: str) -> bytes:
    """Decode a base64url JWT segment (padding-tolerant) for header inspection."""
    pad = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + pad)


class Verifier(Protocol):
    """A bearer-token verifier seam: returns verified claims or raises."""

    async def verify(self, token: str) -> dict[str, Any]: ...


class OidcVerifier:
    """Verifies OIDC / OAuth2 JWT access tokens against an issuer's JWKS (SEC-01).

    Signature is checked against the issuer JWKS; ``iss``/``aud``/``exp``/``nbf``
    are validated. The JWKS is fetched once over httpx and cached.
    """

    # Explicit asymmetric signature allowlist (IAM-02). alg=none and any symmetric
    # (HS*) algorithm are rejected outright - never inferred from the JWKS - so an
    # RS256->HS256 / alg=none confusion cannot forge a token.
    _ALLOWED_ALGS = ("RS256", "RS384", "RS512", "ES256", "ES384", "ES512")
    # A token may not claim a longer life than this regardless of its exp (IAM-03).
    _MAX_LIFETIME = 24 * 3600
    # Minimum interval between FORCED JWKS refetches (IAM-05): an unauthenticated
    # request with a bogus kid must not amplify into an outbound IdP fetch per
    # request.
    _FORCE_REFETCH_MIN_INTERVAL = 30.0

    def __init__(
        self,
        issuer: str,
        audience: str,
        jwks_uri: str,
        *,
        http_client: httpx.AsyncClient | None = None,
        leeway: int = 60,
        jwks_ttl: int = 600,
        allowed_algs: tuple[str, ...] | None = None,
    ) -> None:
        self.issuer = issuer
        self.audience = audience
        self.jwks_uri = jwks_uri
        self._http = http_client
        # Clamp leeway to <=120s (IAM-03): no token gets unbounded clock slack.
        self._leeway = max(0, min(int(leeway), 120))
        self._algs = tuple(allowed_algs or self._ALLOWED_ALGS)
        self._jwks_ttl = jwks_ttl
        self._jwks: dict[str, Any] | None = None
        self._jwks_at: float = 0.0

    async def _fetch_jwks(self) -> dict[str, Any]:
        client = self._http or httpx.AsyncClient(timeout=10.0)  # explicit timeout (IAM-05)
        try:
            resp = await client.get(self.jwks_uri)  # TLS verified by httpx default
            resp.raise_for_status()
            return resp.json()
        finally:
            if self._http is None:
                await client.aclose()

    async def _load_jwks(self, *, force: bool = False) -> dict[str, Any]:
        # JWKS cache with a TTL + forced refetch on a kid miss (IAM-05).
        now = time.monotonic()
        if force or self._jwks is None or (now - self._jwks_at) > self._jwks_ttl:
            self._jwks = await self._fetch_jwks()
            self._jwks_at = now
        return self._jwks

    def _kid(self, token: str) -> str | None:
        try:
            header = json.loads(_b64url(token.split(".", 1)[0]))
            return header.get("kid")
        except Exception:
            return None

    def _kid_present(self, jwks: dict[str, Any], kid: str | None) -> bool:
        if kid is None:
            return True  # let the verifier resolve a single-key JWKS
        return any(k.get("kid") == kid for k in (jwks.get("keys") or []))

    async def verify(self, token: str) -> dict[str, Any]:
        """Verify ``token`` and return its claims, or raise on any failure."""
        jwt = _load_authlib_jwt(list(self._algs))  # alg allowlist pinned (IAM-02)
        kid = self._kid(token)
        jwks = await self._load_jwks()
        if not self._kid_present(jwks, kid):  # kid miss -> refetch then fail closed
            # Throttle forced refetches (_FORCE_REFETCH_MIN_INTERVAL, IAM-05): a
            # bogus-kid request storm re-checks the CACHED set instead of fetching.
            if time.monotonic() - self._jwks_at >= self._FORCE_REFETCH_MIN_INTERVAL:
                jwks = await self._load_jwks(force=True)
            if not self._kid_present(jwks, kid):
                raise HTTPException(status_code=401, detail="unknown signing key")
        # IAM-02: pin the algorithm allowlist; iat/exp/nbf essential (IAM-03).
        claims_options = {
            "iss": {"essential": True, "value": self.issuer},
            "aud": {"essential": True, "value": self.audience},
            "exp": {"essential": True},   # reject a token with no expiry (IAM-03)
        }
        try:
            claims = jwt.decode(token, jwks, claims_options=claims_options)
            claims.validate(leeway=self._leeway)  # exp / nbf / iat / iss / aud
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=401, detail="invalid token") from exc
        data = dict(claims)
        # IAM-04: accept access tokens only - reject an ID token presented as one.
        token_use = data.get("token_use") or data.get("typ")
        if token_use is not None and str(token_use).lower() in {"id", "id_token"}:
            raise HTTPException(status_code=401, detail="id token is not an access token")
        # IAM-03: cap absolute lifetime regardless of the token's own exp.
        iat, exp = data.get("iat"), data.get("exp")
        if isinstance(iat, (int, float)) and isinstance(exp, (int, float)):
            if exp - iat > self._MAX_LIFETIME:
                raise HTTPException(status_code=401, detail="token lifetime too long")
        # A missing/non-numeric iat must not let a far-future exp sail through:
        # cap exp absolutely (exp <= now + _MAX_LIFETIME) as well.
        if isinstance(exp, (int, float)) and exp - time.time() > self._MAX_LIFETIME:
            raise HTTPException(status_code=401, detail="token lifetime too long")
        return data


class SamlVerifier:
    """SAML assertion verification seam (US-IAM-01).

    A placeholder for SAML-federated tenants: plug a concrete implementation
    (signature + audience + condition validation) via ``assertion_validator``.
    Kept as a seam so the OIDC path ships without a SAML stack. Until a validator
    is wired and selected, ``verify`` fails closed; the manifest loader also
    rejects ``identity.provider: saml`` so an operator cannot silently believe
    SAML is enforced (audit finding M13).
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
    store: Any | None = None,
) -> PrincipalResolver:
    """Build a production ``PrincipalResolver`` from a verifier (US-IAM-01/02).

    The returned resolver extracts the bearer, verifies it, derives the platform
    role + scope from the token's groups (US-IAM-02), and builds a ``Principal``
    whose grants are the scope's GrantSet ceiling. Tenant and subject come from
    the verified token / pinned tenant, never from the request body (SEC-02).

    When a ``store`` is supplied, the resolver provisions the user just-in-time
    (US-USR-01): an unmapped, un-invited identity is denied (fail-closed), an
    invited identity is provisioned with its intended role/scope (US-USR-02), and
    the user's *current* (possibly admin-adjusted or deactivated) role/scope/status
    is authoritative - so deactivation revokes access at once (US-USR-03).
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

        groups = _claim_groups(claims)
        if store is not None:
            from .provisioning import current_grants_for_user, provision_user

            user = await provision_user(
                store,
                tenant_id=tenant_id,
                subject=str(subject),
                email=claims.get("email"),
                groups=groups,
                mappings=mappings,
            )
            if user is None or user.status != "active":
                # Unmapped + un-invited, or deactivated -> denied (US-USR-01/03).
                raise HTTPException(status_code=403, detail="no access for this identity")
            return Principal(
                tenant_id=tenant_id,
                subject=user.id,
                grants=current_grants_for_user(user),
                role=user.role,
                actor_tier="human",
                on_behalf_of=_on_behalf_of(claims),
                scope=user.scope,
                credential_kind="federated",
            )

        role, scope = resolve_role(groups, mappings)
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


def _cf_access_assertion(request: Request) -> str:
    """The Cloudflare Access JWT for this request. Cloudflare injects it as the
    ``Cf-Access-Jwt-Assertion`` header on every request to a protected hostname;
    the ``CF_Authorization`` cookie is the browser fallback."""
    token = request.headers.get("cf-access-jwt-assertion", "").strip()
    if token:
        return token
    cookie = request.cookies.get("CF_Authorization", "").strip()
    if cookie:
        return cookie
    raise HTTPException(status_code=401, detail="missing Cloudflare Access assertion")


# The console's product access tiers. All three see the whole tenant; they are
# differentiated by can_author (superadmin/admin author + administer, member does
# not - see rbac.AUTHOR_ROLES) and, for high-consequence verbs, by the HITL gate
# that applies to everyone. superadmin is the owner tier (reserved for roster
# management). An email mapped to anything outside this set is denied.
CF_ACCESS_TIERS: tuple[str, ...] = ("superadmin", "admin", "member")


def build_cf_access_resolver(
    *,
    verifier: Verifier,
    tenant_id: str,
    role_map: dict[str, str],
    default_role: str = DEFAULT_ROLE,
) -> PrincipalResolver:
    """Build a ``PrincipalResolver`` backed by Cloudflare Access (zero-trust edge).

    Cloudflare Access handles login / MFA / SSO at the edge and signs a JWT it
    injects per request. This resolver verifies that JWT against CF's JWKS (via
    ``verifier``, an ``OidcVerifier`` pointed at the team's certs) and derives the
    principal from the authenticated ``email`` claim - identity comes only from
    the verified assertion, never from the request (SEC-01/02). The email is
    mapped to a platform role (``role_map``; ``default_role`` for an
    authenticated-but-unmapped email). An unmapped/``none`` role is denied
    fail-closed (K-13), even though Access already gated who reached the origin -
    defence in depth.
    """
    role_map = {k.strip().lower(): v for k, v in (role_map or {}).items()}

    async def resolver(request: Request) -> Principal:
        token = _cf_access_assertion(request)
        try:
            claims = await verifier.verify(token)
        except HTTPException:
            raise
        except Exception as exc:  # verification failure -> 401 (fail-closed)
            raise HTTPException(
                status_code=401, detail="Access assertion verification failed"
            ) from exc

        email = str(claims.get("email") or "").strip().lower()
        if not email:
            raise HTTPException(status_code=401, detail="Access assertion has no email claim")

        role = role_map.get(email, default_role)
        if role not in CF_ACCESS_TIERS:
            # Unmapped / none / an unknown tier -> denied fail-closed (K-13),
            # even though Access already gated who reached the origin.
            raise HTTPException(status_code=403, detail=f"{email} is not authorized")

        scope = {"all": True}  # tenant-wide; can_author + HITL differentiate the tiers
        return Principal(
            tenant_id=tenant_id,
            subject=email,
            grants=grants_for_scope(scope),
            role=role,
            actor_tier="human",
            scope=scope,
        )

    return resolver


async def dev_principal_resolver(request: Request) -> Principal:
    """Header-trusting resolver for LOCAL DEV ONLY (mirrors the kernel default).

    WARNING: trusts ``x-boltrig-*`` headers with no verification. Production MUST
    use ``build_principal_resolver`` with a real verifier (SEC-01/02); never
    expose this resolver on a network-reachable deployment.
    """
    from boltrig.models import GrantSet

    h = request.headers
    grants = [g for g in h.get("x-boltrig-grants", "").split(",") if g]
    return Principal(
        tenant_id=h.get("x-boltrig-tenant", "default"),
        subject=h.get("x-boltrig-subject", "dev"),
        grants=GrantSet.of(grants),
        role=h.get("x-boltrig-role", "org-admin"),
        actor_tier=h.get("x-boltrig-tier", "human"),
        on_behalf_of=h.get("x-boltrig-obo"),
    )
