"""Static backup-policy checks for the production doctor."""

from __future__ import annotations

import re
from collections.abc import Mapping
from urllib.parse import unquote, urlsplit

from boltrig.config.environment import is_truthy

DoctorResult = tuple[str, str, str, str]

_DATABASE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_DATABASE_SET_RE = re.compile(r"^[A-Za-z0-9_-]+(?:,[A-Za-z0-9_-]+)*$")


def _result(
    status: str, name: str, message: str, hint: str = ""
) -> DoctorResult:
    return status, name, message, hint


def _database_name_from_dsn(dsn: str, *, key: str) -> tuple[str | None, str | None]:
    """Return one safe database name without ever reflecting DSN credentials."""
    try:
        parsed = urlsplit(dsn)
    except ValueError:
        return None, f"{key} is not a valid PostgreSQL DSN."
    scheme = parsed.scheme.lower()
    if scheme not in {"postgres", "postgresql"} and not scheme.startswith(
        "postgresql+"
    ):
        return None, f"{key} is not a PostgreSQL DSN."
    if not parsed.path.startswith("/"):
        return None, f"{key} does not name a database."
    name = unquote(parsed.path[1:])
    if not _DATABASE_NAME_RE.fullmatch(name):
        return None, f"{key} must name exactly one safe database."
    return name, None


def _configured_database_name(
    env: Mapping[str, str],
    *,
    dsn_key: str,
    name_keys: tuple[str, ...],
    default: str | None = None,
) -> tuple[str | None, str | None]:
    names: list[tuple[str, str]] = []
    dsn = str(env.get(dsn_key) or "")
    if dsn:
        name, error = _database_name_from_dsn(dsn, key=dsn_key)
        if error:
            return None, error
        assert name is not None
        names.append((dsn_key, name))
    for key in name_keys:
        value = str(env.get(key) or "")
        if not value:
            continue
        if not _DATABASE_NAME_RE.fullmatch(value):
            return None, f"{key} must be one safe database name."
        names.append((key, value))
    if not names:
        return default, None
    if len({name for _, name in names}) != 1:
        sources = ", ".join(key for key, _ in names)
        return None, f"Database sources disagree: {sources}."
    return names[0][1], None


def _configured_backup_databases(
    env: Mapping[str, str], *, application_database: str | None
) -> tuple[tuple[str, ...] | None, str | None]:
    raw = env.get("BACKUP_DATABASES")
    if raw is None or raw == "":
        if application_database is None:
            return None, "BACKUP_DATABASES is unset and the application database is unknown."
        raw = application_database
    if not _DATABASE_SET_RE.fullmatch(raw):
        return None, "BACKUP_DATABASES is not a safe comma-separated database set."
    databases = tuple(raw.split(","))
    if len(set(databases)) != len(databases):
        return None, "BACKUP_DATABASES contains duplicate database names."
    return databases, None


def _storage_checks(env: Mapping[str, str], production: bool) -> list[DoctorResult]:
    checks: list[DoctorResult] = []
    if env.get("BACKUP_REMOTE"):
        checks.append(_result("ok", "backup_remote", "Off-box backup remote is configured."))
    else:
        checks.append(
            _result(
                "fail" if production else "warn",
                "backup_remote",
                "BACKUP_REMOTE is unset; scheduled backups remain local-only.",
                "Set BACKUP_REMOTE or document an equivalent off-box backup path.",
            )
        )
    if production and not env.get("BACKUP_PASSPHRASE"):
        checks.append(
            _result(
                "fail",
                "backup_encryption",
                "BACKUP_PASSPHRASE is unset; Hatchet signing state cannot be backed up safely.",
            )
        )
    elif env.get("BACKUP_PASSPHRASE"):
        checks.append(
            _result("ok", "backup_encryption", "Backup encryption is configured.")
        )
    return checks


def _configuration_problems(
    *,
    status: str,
    application_database: str | None,
    application_error: str | None,
    hatchet_required: bool,
    hatchet_database: str | None,
    hatchet_error: str | None,
    databases: tuple[str, ...] | None,
    databases_error: str | None,
) -> list[DoctorResult]:
    checks: list[DoctorResult] = []
    if application_error or application_database is None:
        checks.append(
            _result(
                status,
                "backup_application_database",
                application_error
                or "The application database cannot be derived from configuration.",
                "Set DATABASE_URL and any POSTGRES_DB/PGDATABASE aliases to the same safe database name.",
            )
        )
    if hatchet_required and (hatchet_error or hatchet_database is None):
        checks.append(
            _result(
                status,
                "backup_hatchet_database",
                hatchet_error
                or "The Hatchet database cannot be derived from configuration.",
                "Set HATCHET_DATABASE_URL and HATCHET_DATABASE_NAME to the same safe database name.",
            )
        )
    if databases_error or databases is None:
        checks.append(
            _result(
                status,
                "backup_databases",
                databases_error or "The backup database set cannot be derived.",
                "Set BACKUP_DATABASES to exact, comma-separated database names without spaces.",
            )
        )
    return checks


def _coverage_problems(
    *,
    status: str,
    application_database: str | None,
    hatchet_required: bool,
    hatchet_database: str | None,
    databases: tuple[str, ...] | None,
) -> list[DoctorResult]:
    if databases is None:
        return []
    checks: list[DoctorResult] = []
    if application_database is not None and application_database not in databases:
        checks.append(
            _result(
                status,
                "backup_application_database",
                "BACKUP_DATABASES omits the configured application database.",
                "Include the exact database named by DATABASE_URL in BACKUP_DATABASES.",
            )
        )
    if hatchet_required and hatchet_database and hatchet_database not in databases:
        checks.append(
            _result(
                status,
                "backup_hatchet_database",
                "BACKUP_DATABASES omits the configured Hatchet database.",
                "Include the exact database named by HATCHET_DATABASE_URL/HATCHET_DATABASE_NAME.",
            )
        )
    return checks


def _database_coverage_checks(
    env: Mapping[str, str], production: bool
) -> list[DoctorResult]:
    status = "fail" if production else "warn"
    application_database, application_error = _configured_database_name(
        env, dsn_key="DATABASE_URL", name_keys=("POSTGRES_DB", "PGDATABASE")
    )
    hatchet_required = production or any(
        env.get(key)
        for key in (
            "HATCHET_CLIENT_TOKEN",
            "HATCHET_DATABASE_URL",
            "HATCHET_DATABASE_NAME",
        )
    ) or is_truthy(env.get("BOLTRIG_REQUIRE_DURABLE"))
    hatchet_database, hatchet_error = _configured_database_name(
        env,
        dsn_key="HATCHET_DATABASE_URL",
        name_keys=("HATCHET_DATABASE_NAME",),
        default="hatchet" if hatchet_required else None,
    )
    databases, databases_error = _configured_backup_databases(
        env, application_database=application_database
    )
    details = {
        "status": status,
        "application_database": application_database,
        "hatchet_required": hatchet_required,
        "hatchet_database": hatchet_database,
        "databases": databases,
    }
    checks = _configuration_problems(
        **details,
        application_error=application_error,
        hatchet_error=hatchet_error,
        databases_error=databases_error,
    )
    checks.extend(_coverage_problems(**details))
    if not checks:
        checks.append(
            _result(
                "ok",
                "backup_databases",
                "The exact application and Hatchet databases are in the backup set.",
            )
        )
    return checks


def backup_checks(
    env: Mapping[str, str], production: bool
) -> tuple[DoctorResult, ...]:
    """Return redacted static checks for backup storage and database coverage."""
    return tuple((*_storage_checks(env, production), *_database_coverage_checks(env, production)))


__all__ = ["backup_checks"]
