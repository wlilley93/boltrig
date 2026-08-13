"""Static production-readiness checks with no dependency I/O."""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import parse_qs, urlsplit

from boltrig.api.doctor_backups import backup_checks
from boltrig.api.doctor_codex import codex_release_check
from boltrig.api.doctor_stack_state import stack_state_checks
from boltrig.config.environment import is_truthy
from boltrig.config.manifest import FleetManifest, load_manifest

# [2026] VJS-CC-BOLTRIG-AUDIT-KEY-PROVISIONING-001 O2: ONE placeholder predicate,
# shared with the bootstrap audit-key guard and the readiness-receipt key, so the
# three sites cannot disagree about what counts as a placeholder again.
from boltrig.config.weak_secrets import (
    PLACEHOLDER_FRAGMENTS as _PLACEHOLDER_FRAGMENTS,
    is_weak_secret as _is_weak_secret,
)

_PROD_NAMES = {"prod", "production", "staging"}
_LOCAL_HOSTS = {
    "localhost",
    "127.0.0.1",
    "::1",
    "postgres",
    "redis",
    "kernel",
    "bifrost",
    "local-model",
}
_HOSTED_MODEL_KINDS = {"anthropic", "openai"}
_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    status: str
    message: str
    hint: str = ""


@dataclass(frozen=True)
class DoctorReport:
    production: bool
    checks: tuple[DoctorCheck, ...]

    @property
    def failed(self) -> bool:
        return any(c.status == "fail" for c in self.checks)

    @property
    def exit_code(self) -> int:
        return 1 if self.failed else 0

    def to_json(self) -> str:
        return json.dumps(
            {"production": self.production, "checks": [asdict(c) for c in self.checks]},
            indent=2,
            sort_keys=True,
        )


def load_env_file(path: str | os.PathLike[str], *, base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Merge a simple dotenv file over ``base``.

    This supports the committed ``.env.example`` style: ``KEY=value``, optional
    ``export`` prefix, quotes, blank lines and comments. It deliberately does not
    execute shell syntax.
    """
    env = dict(base or {})
    p = Path(path)
    if not p.exists():
        return env
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        key, sep, value = line.partition("=")
        key = key.strip()
        if sep != "=" or not _KEY_RE.match(key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        env[key] = value
    return env


def run_doctor(
    *,
    env: Mapping[str, str] | None = None,
    manifest_path: str | os.PathLike[str] | None = None,
    production: bool = False,
) -> DoctorReport:
    e = dict(os.environ if env is None else env)
    prod = production or _production_signal(e)
    checks: list[DoctorCheck] = []

    _check_datastores(e, prod, checks)
    _check_auth(e, prod, checks)
    _check_edge(e, prod, checks)
    manifest = _check_manifest(e, prod, manifest_path, checks)
    _check_runtime(e, prod, checks, manifest)
    if manifest is not None:
        _check_stack_tool_state(e, prod, manifest, checks)
        _check_model_posture(e, prod, manifest, checks)
        _check_memory_posture(prod, manifest, checks)
        if codex_check := codex_release_check(e, prod, manifest):
            _add(checks, *codex_check)
    for backup_check in backup_checks(e, prod):
        _add(checks, *backup_check)
    _check_durable_engine(e, checks)

    return DoctorReport(production=prod, checks=tuple(checks))


def format_report(report: DoctorReport) -> str:
    width = max((len(c.name) for c in report.checks), default=8)
    lines = [
        f"Boltrig doctor ({'production' if report.production else 'development'} mode)",
        "",
    ]
    for check in report.checks:
        lines.append(f"[{check.status.upper():4}] {check.name:<{width}}  {check.message}")
        if check.hint:
            lines.append(f"       hint: {check.hint}")
    failed = sum(1 for c in report.checks if c.status == "fail")
    warned = sum(1 for c in report.checks if c.status == "warn")
    lines.extend(["", f"Summary: {failed} fail, {warned} warn, {len(report.checks)} checks"])
    return "\n".join(lines)


def _add(
    checks: list[DoctorCheck],
    status: str,
    name: str,
    message: str,
    hint: str = "",
) -> None:
    checks.append(DoctorCheck(name=name, status=status, message=message, hint=hint))


def _csv(value: str | None) -> list[str]:
    return [p.strip() for p in (value or "").split(",") if p.strip()]


def _production_signal(env: Mapping[str, str]) -> bool:
    if is_truthy(env.get("BOLTRIG_PRODUCTION")):
        return True
    return any((env.get(k) or "").strip().lower() in _PROD_NAMES for k in ("ENV", "BOLTRIG_ENV", "APP_ENV"))


def _weak(value: str | None, *, min_len: int = 24) -> bool:
    return _is_weak_secret(value, min_len=min_len)


def _host(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlsplit(url)
    return parsed.hostname


def _is_local_host(host: str | None) -> bool:
    if not host:
        return False
    if host in _LOCAL_HOSTS:
        return True
    if host.endswith(".local") or host.endswith(".internal"):
        return True
    return host.startswith("127.")


def _check_datastores(env: Mapping[str, str], prod: bool, checks: list[DoctorCheck]) -> None:
    database_url = (env.get("DATABASE_URL") or "").strip()
    if not database_url:
        _add(
            checks,
            "fail" if prod else "warn",
            "database_url",
            "DATABASE_URL is unset; durable state will not use Postgres.",
            "Set DATABASE_URL to the Postgres DSN used by kernel and fleet.",
        )
    elif any(fragment in database_url for fragment in _PLACEHOLDER_FRAGMENTS):
        _add(checks, "fail", "database_url", "DATABASE_URL still contains a placeholder.")
    else:
        _add(checks, "ok", "database_url", "DATABASE_URL is set.")
        if prod and database_url.startswith("postgres") and "sslmode=require" not in database_url:
            _add(
                checks,
                "warn",
                "postgres_tls",
                "DATABASE_URL does not include sslmode=require.",
                "Use TLS for host-spanning Postgres connections.",
            )

    if _weak(env.get("POSTGRES_PASSWORD")):
        _add(
            checks,
            "fail" if prod else "warn",
            "postgres_password",
            "POSTGRES_PASSWORD is empty, short, or placeholder-like.",
            "Generate a deployment-specific password and keep it out of git.",
        )
    else:
        _add(checks, "ok", "postgres_password", "POSTGRES_PASSWORD is non-placeholder.")

    if env.get("REDIS_URL"):
        _add(checks, "ok", "redis_url", "REDIS_URL is set.")
    else:
        _add(
            checks,
            "fail" if prod else "warn",
            "redis_url",
            "REDIS_URL is unset; distributed rate-limit/counter state may degrade.",
        )

    if _weak(env.get("BOLTRIG_AUDIT_HMAC_KEY"), min_len=32):
        _add(
            checks,
            "fail" if prod else "warn",
            "audit_hmac_key",
            "BOLTRIG_AUDIT_HMAC_KEY is missing or placeholder-like.",
            "Generate a long random value for the audit hash chain.",
        )
    else:
        _add(checks, "ok", "audit_hmac_key", "Audit HMAC key is non-placeholder.")

    secret_store = (env.get("SECRET_STORE") or "env").strip().lower()
    if prod and secret_store == "env":
        _add(
            checks,
            "warn",
            "secret_store",
            "SECRET_STORE=env; production should prefer Vault/KMS/docker secrets.",
        )
    else:
        _add(checks, "ok", "secret_store", f"SECRET_STORE={secret_store}.")


def _check_auth(env: Mapping[str, str], prod: bool, checks: list[DoctorCheck]) -> None:
    dev_auth = is_truthy(env.get("BOLTRIG_DEV_AUTH"))
    oidc_values = [env.get("OIDC_ISSUER"), env.get("OIDC_AUDIENCE"), env.get("OIDC_JWKS_URI")]
    oidc_any = any(oidc_values)
    oidc_all = all(oidc_values) and not any(_weak(v, min_len=3) for v in oidc_values)
    cf_values = [env.get("CF_ACCESS_TEAM_DOMAIN"), env.get("CF_ACCESS_AUD")]
    cf_any = any(cf_values)
    cf_all = all(cf_values) and not any(_weak(v, min_len=3) for v in cf_values)
    session_auth = (env.get("BOLTRIG_AUTH_MODE") or "").strip().lower() == "session"

    if dev_auth and prod:
        _add(checks, "fail", "dev_auth", "BOLTRIG_DEV_AUTH is enabled in production mode.")
    elif dev_auth:
        _add(checks, "ok", "dev_auth", "Development header auth is enabled.")
    else:
        _add(checks, "ok", "dev_auth", "Development header auth is disabled.")

    if oidc_any and not oidc_all:
        _add(checks, "fail" if prod else "warn", "oidc", "OIDC config is partial or placeholder-like.")
    elif oidc_all:
        _add(checks, "ok", "oidc", "OIDC issuer, audience, and JWKS URI are configured.")

    if cf_any and not cf_all:
        _add(
            checks,
            "fail" if prod else "warn",
            "cf_access",
            "Cloudflare Access config is partial or placeholder-like.",
        )
    elif cf_all:
        _add(checks, "ok", "cf_access", "Cloudflare Access team domain and AUD are configured.")
        if (env.get("CF_ACCESS_DEFAULT_ROLE") or "none").strip().lower() != "none":
            _add(
                checks,
                "warn",
                "cf_default_role",
                "CF_ACCESS_DEFAULT_ROLE is not fail-closed.",
                "Use CF_ACCESS_DEFAULT_ROLE=none unless every Access-authenticated user is allowed.",
            )

    if oidc_all or cf_all or session_auth:
        _add(checks, "ok", "auth_mode", "A real authentication mode is configured.")
    elif dev_auth and not prod:
        _add(checks, "ok", "auth_mode", "Only development auth is configured.")
    else:
        _add(
            checks,
            "fail" if prod else "warn",
            "auth_mode",
            "No real auth mode is configured; the kernel will fail closed.",
            "Configure OIDC, Cloudflare Access, or BOLTRIG_AUTH_MODE=session.",
        )

    if session_auth:
        # The session cookie is the bearer of authority under session auth; the
        # knob defaults to Secure (settings.py) so only an EXPLICIT opt-out is
        # flagged here.
        cookie_secure = env.get("BOLTRIG_SESSION_COOKIE_SECURE")
        if cookie_secure is not None and not is_truthy(cookie_secure):
            _add(
                checks,
                "fail" if prod else "warn",
                "session_cookie_secure",
                "BOLTRIG_SESSION_COOKIE_SECURE is disabled under session auth.",
                "Session cookies without Secure ride plaintext HTTP; unset the knob or set it true.",
            )
        else:
            _add(checks, "ok", "session_cookie_secure", "Session cookies are Secure.")


def _check_edge(env: Mapping[str, str], prod: bool, checks: list[DoctorCheck]) -> None:
    hosts = _csv(env.get("BOLTRIG_ALLOWED_HOSTS"))
    if prod and (not hosts or hosts == ["*"]):
        _add(
            checks,
            "fail",
            "allowed_hosts",
            "BOLTRIG_ALLOWED_HOSTS is unset or wildcard in production mode.",
        )
    elif hosts:
        _add(checks, "ok", "allowed_hosts", "Host allowlist is explicit.")
    else:
        _add(checks, "warn", "allowed_hosts", "BOLTRIG_ALLOWED_HOSTS is unset; dev wildcard applies.")

    origins = _csv(env.get("BOLTRIG_CORS_ORIGINS"))
    if "*" in origins:
        _add(checks, "fail", "cors_origins", "BOLTRIG_CORS_ORIGINS contains '*'.")
    elif origins:
        _add(checks, "ok", "cors_origins", "Browser CORS origins are explicit.")
    else:
        _add(checks, "ok", "cors_origins", "CORS is same-origin by default.")

    max_body = env.get("BOLTRIG_MAX_BODY_BYTES")
    if max_body:
        try:
            if int(max_body) <= 0:
                raise ValueError
            _add(checks, "ok", "body_cap", "Request body cap is set.")
        except ValueError:
            _add(checks, "warn", "body_cap", "BOLTRIG_MAX_BODY_BYTES is not a positive integer.")

    if prod and not env.get("BOLTRIG_DOMAIN"):
        _add(
            checks,
            "warn",
            "tls_domain",
            "BOLTRIG_DOMAIN is unset; doctor cannot confirm secure overlay intent.",
            "Use make secure-up or set equivalent edge TLS outside compose.",
        )


# Runtime kinds that have been REMOVED from the codebase, not merely gated off.
# A capability or manifest still naming one degrades to the typed unavailable
# result rather than crashing (P9), so this is drift to report, never a deploy
# blocker. `pi` (PC-20 L1) and `hermes` (2026-08-06) are both retired; see
# docs/decisions/0020-retire-the-pi-lane.md. This tuple only ever GROWS.
_RETIRED_RUNTIMES = ("pi", "hermes")


def _check_runtime(
    env: Mapping[str, str],
    prod: bool,
    checks: list[DoctorCheck],
    manifest: FleetManifest | None,
) -> None:
    """Report a manifest still enabling a runtime this build no longer has.

    Until the Pi retirement this function checked the sidecar's URL, bearer and
    egress allow-list. Those checks went with the lane. What replaces them is the
    check the retirement actually creates a need for: a tenant manifest OUTLIVES
    the image, so a provisioned tenant can keep asking for `runtimes.pi` long
    after nothing can serve it. Measured on the Classical Visas tenant the day the
    lane was retired: `runtimes.pi.enabled: true`, pointing at a sidecar that no
    longer exists, and nothing anywhere said so.
    """
    if manifest is None:
        return
    runtimes = manifest.section("runtimes")
    for kind in _RETIRED_RUNTIMES:
        entry = runtimes.get(kind)
        if not isinstance(entry, dict):
            continue
        if not is_truthy(str(entry.get("enabled", False))):
            continue
        _add(
            checks,
            "warn",
            f"retired_runtime_{kind}",
            f"Manifest enables the retired '{kind}' runtime; capabilities asking for "
            f"it degrade. Remove the runtimes.{kind} block.",
        )


def _check_manifest(
    env: Mapping[str, str],
    prod: bool,
    manifest_path: str | os.PathLike[str] | None,
    checks: list[DoctorCheck],
) -> FleetManifest | None:
    if manifest_path is None:
        _add(checks, "warn", "manifest", "No manifest path was provided; manifest checks skipped.")
        return None
    path = Path(manifest_path)
    if not path.exists():
        _add(
            checks,
            "fail" if prod else "warn",
            "manifest",
            f"{path} does not exist; manifest checks skipped.",
        )
        return None
    try:
        manifest = load_manifest(str(path), env=env)
    except Exception as exc:
        _add(checks, "fail", "manifest", f"Manifest failed to load: {type(exc).__name__}: {exc}")
        return None
    _add(checks, "ok", "manifest", f"Manifest loaded for tenant {manifest.tenant_id}.")
    return manifest


def _check_stack_tool_state(
    env: Mapping[str, str],
    prod: bool,
    manifest: FleetManifest,
    checks: list[DoctorCheck],
) -> None:
    for check in stack_state_checks(env, production=prod, manifest=manifest):
        _add(checks, check.status, check.name, check.message, check.hint)


def _check_model_posture(
    env: Mapping[str, str],
    prod: bool,
    manifest: FleetManifest,
    checks: list[DoctorCheck],
) -> None:
    endpoints = {ep.id: ep for ep in manifest.models.endpoints}
    if not endpoints:
        _add(checks, "fail" if prod else "warn", "model_endpoints", "Manifest has no model endpoints.")
        return
    _add(checks, "ok", "model_endpoints", f"Manifest declares {len(endpoints)} model endpoint(s).")

    sensitive_id = manifest.models.sensitive_endpoint
    sensitive_ep = endpoints.get(sensitive_id or "")
    if sensitive_ep is None:
        _add(
            checks,
            "fail" if prod else "warn",
            "sensitive_endpoint",
            "models.sensitive_endpoint does not name a declared endpoint.",
        )
    elif sensitive_ep.data_class != "sensitive":
        _add(checks, "fail", "sensitive_endpoint", "Sensitive endpoint is not data_class=sensitive.")
    else:
        _add(checks, "ok", "sensitive_endpoint", "Sensitive model route points at a sensitive endpoint.")
        host = _host(sensitive_ep.base_url)
        if host and not _is_local_host(host):
            _add(
                checks,
                "warn",
                "sensitive_endpoint_host",
                "Sensitive endpoint base_url is not obviously local/internal.",
            )

    air_gapped = is_truthy(env.get("AIR_GAPPED")) or manifest.network.air_gapped
    if air_gapped:
        hosted = [
            ep.id
            for ep in endpoints.values()
            if ep.data_class != "sensitive"
            and ep.kind in _HOSTED_MODEL_KINDS
            and not _is_local_host(_host(ep.base_url))
        ]
        if hosted:
            _add(
                checks,
                "fail" if prod else "warn",
                "air_gapped_models",
                f"Air-gapped mode has hosted standard endpoint(s): {', '.join(hosted)}.",
            )
        else:
            _add(checks, "ok", "air_gapped_models", "Air-gapped model endpoints look local.")

    gateway_url = env.get("BOLTRIG_MODEL_GATEWAY_URL") or _manifest_gateway_url(manifest)
    if gateway_url:
        split = urlsplit(gateway_url)
        if not split.scheme or not split.netloc:
            _add(checks, "fail", "model_gateway", "Model gateway URL is malformed.")
        elif not gateway_url.rstrip("/").endswith("/v1"):
            _add(checks, "warn", "model_gateway", "Model gateway URL should include the /v1 base path.")
        elif not _is_local_host(split.hostname):
            _add(checks, "warn", "model_gateway", "Model gateway host is not obviously internal.")
        else:
            _add(checks, "ok", "model_gateway", "Model gateway URL is internal-looking.")
    else:
        _add(checks, "warn", "model_gateway", "Model gateway is not configured; cache/cost seam is inert.")


def _check_memory_posture(prod: bool, manifest: FleetManifest, checks: list[DoctorCheck]) -> None:
    memory = manifest.section("memory")
    if not is_truthy(str(memory.get("enabled", False))):
        return
    endpoints = {ep.id: ep for ep in manifest.models.endpoints}
    local_ids = {str(v) for v in memory.get("local_endpoints") or []}
    embedding = str(memory.get("embedding_endpoint") or "")
    extraction = str(memory.get("extraction_endpoint") or "")

    bad = [
        endpoint_id
        for endpoint_id in (embedding, extraction)
        if endpoint_id and (
            endpoint_id not in local_ids or endpoints.get(endpoint_id, None) is None
            or endpoints[endpoint_id].data_class != "sensitive"
        )
    ]
    if bad:
        _add(checks, "fail", "memory_residency", f"Memory endpoint(s) are not local-sensitive: {bad}.")
    else:
        _add(checks, "ok", "memory_residency", "Memory endpoints are local-sensitive.")

    if prod and str(memory.get("engine", "")).lower() == "local":
        _add(
            checks,
            "warn",
            "memory_engine",
            "memory.engine=local; Boltrig v2 production usually wants Mem0 primary"
            " with Cognee as an optional projection.",
        )
    if not is_truthy(str((memory.get("ingest") or {}).get("screen_content", False))):
        _add(checks, "warn", "memory_screening", "Memory ingest content screening is disabled.")


def _manifest_gateway_url(manifest: FleetManifest) -> str | None:
    runtimes = manifest.section("runtimes")
    gateway = runtimes.get("gateway") if isinstance(runtimes.get("gateway"), dict) else {}
    value = gateway.get("base_url") if isinstance(gateway, dict) else None
    return str(value) if value else None


def _check_durable_engine(env: Mapping[str, str], checks: list[DoctorCheck]) -> None:
    if env.get("HATCHET_CLIENT_TOKEN") or _hatchet_dsn_has_password(env.get("HATCHET_DATABASE_URL")):
        _add(checks, "ok", "hatchet", "Hatchet durable-engine wiring is present.")
    else:
        _add(checks, "warn", "hatchet", "Hatchet live engine wiring is absent; local fallback only.")


def _hatchet_dsn_has_password(dsn: str | None) -> bool:
    if not dsn:
        return False
    query = parse_qs(urlsplit(dsn).query)
    return bool(urlsplit(dsn).password or query.get("password"))
