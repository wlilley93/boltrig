"""Static edge and packaged-desktop checks for ``boltrig doctor``."""

from __future__ import annotations

from collections.abc import Mapping


Check = tuple[str, str, str, str]


def _csv(value: str | None) -> list[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def edge_checks(env: Mapping[str, str], production: bool) -> list[Check]:
    """Return content-free edge checks without importing the doctor report types."""
    checks: list[Check] = []
    hosts = _csv(env.get("BOLTRIG_ALLOWED_HOSTS"))
    if production and (not hosts or hosts == ["*"]):
        checks.append((
            "fail", "allowed_hosts",
            "BOLTRIG_ALLOWED_HOSTS is unset or wildcard in production mode.", "",
        ))
    elif hosts:
        checks.append(("ok", "allowed_hosts", "Host allowlist is explicit.", ""))
    else:
        checks.append((
            "warn", "allowed_hosts",
            "BOLTRIG_ALLOWED_HOSTS is unset; dev wildcard applies.", "",
        ))

    origins = _csv(env.get("BOLTRIG_CORS_ORIGINS"))
    if "*" in origins:
        checks.append(("fail", "cors_origins", "BOLTRIG_CORS_ORIGINS contains '*'.", ""))
    elif origins:
        checks.append(("ok", "cors_origins", "Browser CORS origins are explicit.", ""))
    else:
        checks.append(("ok", "cors_origins", "CORS is same-origin by default.", ""))

    desktop_origins = {"tauri://localhost", "https://tauri.localhost"}
    configured_desktop = desktop_origins.intersection(origins)
    if env.get("BOLTRIG_RELEASE_MODE") == "full" and not configured_desktop:
        checks.append((
            "fail", "desktop_cors_origin",
            "A full release has no packaged-desktop origin in BOLTRIG_CORS_ORIGINS.",
            "Add only the exact Tauri origins for the platforms being shipped.",
        ))
    elif configured_desktop:
        checks.append((
            "ok", "desktop_cors_origin",
            "Packaged-desktop CORS origins are explicit.", "",
        ))

    max_body = env.get("BOLTRIG_MAX_BODY_BYTES")
    if max_body:
        try:
            if int(max_body) <= 0:
                raise ValueError
            checks.append(("ok", "body_cap", "Request body cap is set.", ""))
        except ValueError:
            checks.append((
                "warn", "body_cap",
                "BOLTRIG_MAX_BODY_BYTES is not a positive integer.", "",
            ))

    if production and not env.get("BOLTRIG_DOMAIN"):
        checks.append((
            "warn", "tls_domain",
            "BOLTRIG_DOMAIN is unset; doctor cannot confirm secure overlay intent.",
            "Use make secure-up or set equivalent edge TLS outside compose.",
        ))
    return checks
