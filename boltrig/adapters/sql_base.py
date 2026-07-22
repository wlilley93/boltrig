"""Reusable SQL adapter base for ``runtime='sql'`` integrations (US-ADP-03, SEC-09).

Concrete SQL adapters (e.g. a CRM, an ERP, a data warehouse over Postgres /
MySQL / MSSQL / Oracle) subclass this, declare their verbs in :meth:`describe`,
and implement handlers that call ``db.query`` (read) or ``db.execute_write``
(write) on the per-call :class:`_Db` handed to them.

Two invariants are enforced here so they cannot be forgotten per adapter:

  * Parameterised statements only. Caller values are passed as bound parameters
    (``:name``); the SQL text never interpolates a caller value. This is the
    defence against injection (SEC-09).
  * Read / write scope per binding. A binding marked read-only
    (``write_allowed=False``) cannot run a write: the attempt is refused with
    :class:`ErrorClass.UNAUTHORISED` before any statement reaches the driver.

The engine is a thin, lazily-imported seam: SQLAlchemy core executed in a worker
thread (so the async ``execute`` contract is honoured without requiring an async
DB driver). If SQLAlchemy or the dialect driver is missing, or the backend is
unreachable, the adapter degrades to :class:`ErrorClass.UNAVAILABLE` rather than
crashing the kernel (US-ADP-06, P9).
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable
from urllib.parse import quote_plus

from boltrig.adapters.base import (
    AdapterError,
    Credential,
    ErrorClass,
    Result,
    VerbSpec,
)
from boltrig.models import InvocationContext

# A per-verb handler: (params, per-call db handle, context) -> Result.
SqlHandler = Callable[
    [dict[str, Any], "_Db", InvocationContext],
    Awaitable[Result],
]


class _SqlFailure(Exception):
    """Internal carrier so a mapped error can bubble out of a worker thread."""

    def __init__(self, error: AdapterError) -> None:
        super().__init__(error.message)
        self.error = error


class _Db:
    """A per-call database handle bound to one resolved DSN. Handlers receive it
    so the read/write scope and parameterisation invariants are unavoidable."""

    def __init__(self, adapter: "SqlAdapter", dsn: str) -> None:
        self._adapter = adapter
        self._dsn = dsn

    async def query(
        self, sql: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Run a parameterised read. Returns ``{"rows": [...], "count": n}``."""
        return await self._adapter._run(self._dsn, sql, params or {}, write=False)

    async def execute_write(
        self, sql: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Run a parameterised write. Refused if the binding is read-scoped."""
        return await self._adapter._run(self._dsn, sql, params or {}, write=True)


class SqlAdapter:
    """Base class for ``runtime='sql'`` adapters (US-ADP-03)."""

    runtime = "sql"
    id = "sql-adapter"
    version = "1.0.0"

    def __init__(
        self,
        *,
        dsn: str | None = None,
        write_allowed: bool = False,
        dialect: str = "postgresql",
        pool_size: int = 5,
    ) -> None:
        self.dsn = dsn
        self.write_allowed = write_allowed
        self.dialect = dialect
        self.pool_size = pool_size
        self._engines: dict[str, Any] = {}

    # --- contract surface ----------------------------------------------------
    def describe(self) -> list[VerbSpec]:
        raise NotImplementedError

    def _handlers(self) -> dict[str, SqlHandler]:
        """Map verb id -> bound handler. Subclasses override."""
        return {}

    async def execute(
        self,
        verb: str,
        params: dict[str, Any],
        credential: Credential | None,
        context: InvocationContext,
    ) -> Result:
        handler = self._handlers().get(verb)
        if handler is None:
            return Result.failure(
                AdapterError(ErrorClass.INVALID, f"unknown verb {verb}")
            )
        dsn = self._resolve_dsn(credential)
        if not dsn:
            return Result.failure(
                AdapterError(ErrorClass.UNAVAILABLE, "no DSN configured for binding")
            )
        db = _Db(self, dsn)
        try:
            return await handler(params, db, context)
        except _SqlFailure as failure:
            return Result.failure(failure.error)
        except KeyError as missing:
            return Result.failure(
                AdapterError(ErrorClass.INVALID, f"missing parameter {missing}")
            )
        except Exception as exc:  # never crash the kernel (US-ADP-06)
            return Result.failure(
                AdapterError(ErrorClass.INTERNAL, f"adapter error: {type(exc).__name__}")
            )

    async def health(self) -> str:
        dsn = self.dsn or next(iter(self._engines), None)
        if not dsn:
            return "unknown"
        try:
            await self._run(dsn, "SELECT 1", {}, write=False)
            return "ok"
        except _SqlFailure as failure:
            return "down" if failure.error.error_class == ErrorClass.UNAVAILABLE else "degraded"
        except Exception:
            return "down"

    # --- internals -----------------------------------------------------------
    def _resolve_dsn(self, credential: Credential | None) -> str | None:
        """A DSN may ride in on the credential (per-tenant database) or be the
        adapter default. Material is never logged (SEC-05)."""
        if credential is not None:
            material = credential.material
            dsn = material.get("dsn") or material.get("url")
            if isinstance(dsn, str) and dsn:
                return dsn
            built = self._build_dsn(material)
            if built:
                return built
        return self.dsn

    def _build_dsn(self, material: dict[str, Any]) -> str | None:
        host = material.get("host")
        database = material.get("database") or material.get("db")
        if not host or not database:
            return None
        user = material.get("username") or material.get("user") or ""
        password = material.get("password") or ""
        port = material.get("port")
        driver = material.get("driver") or self.dialect
        # URL-quote the credential material: a password containing '@', ':' or
        # '/' would otherwise corrupt the DSN's netloc.
        auth = f"{quote_plus(user)}:{quote_plus(password)}@" if user else ""
        netloc = f"{host}:{port}" if port else host
        return f"{driver}://{auth}{netloc}/{database}"

    async def _run(
        self, dsn: str, sql: str, params: dict[str, Any], write: bool
    ) -> dict[str, Any]:
        if write and not self.write_allowed:
            raise _SqlFailure(
                AdapterError(
                    ErrorClass.UNAUTHORISED,
                    "write not allowed for this binding (read-scoped)",
                )
            )
        return await asyncio.to_thread(self._run_sync, dsn, sql, params, write)

    def _run_sync(
        self, dsn: str, sql: str, params: dict[str, Any], write: bool
    ) -> dict[str, Any]:
        try:
            import sqlalchemy as sa
            from sqlalchemy import exc as sa_exc
        except Exception as exc:  # driver / library absent -> degrade (US-ADP-06)
            raise _SqlFailure(
                AdapterError(
                    ErrorClass.UNAVAILABLE,
                    "sql engine unavailable (sqlalchemy not importable)",
                    retryable=True,
                )
            ) from exc

        engine = self._engine_for(dsn, sa, sa_exc)
        try:
            with engine.connect() as conn:
                result = conn.execute(sa.text(sql), params)
                if write:
                    conn.commit()
                    return {"rowcount": result.rowcount}
                rows = [dict(row._mapping) for row in result]
                return {"rows": rows, "count": len(rows)}
        except sa_exc.IntegrityError as exc:
            raise _SqlFailure(
                AdapterError(ErrorClass.CONFLICT, "integrity violation")
            ) from exc
        except (sa_exc.ProgrammingError, sa_exc.StatementError) as exc:
            raise _SqlFailure(
                AdapterError(ErrorClass.INVALID, "invalid statement or parameters")
            ) from exc
        except (sa_exc.OperationalError, sa_exc.InterfaceError, sa_exc.DBAPIError) as exc:
            raise _SqlFailure(
                AdapterError(ErrorClass.UNAVAILABLE, "database unavailable", retryable=True)
            ) from exc
        except sa_exc.SQLAlchemyError as exc:
            raise _SqlFailure(AdapterError(ErrorClass.INTERNAL, "sql error")) from exc

    def _engine_for(self, dsn: str, sa: Any, sa_exc: Any) -> Any:
        engine = self._engines.get(dsn)
        if engine is not None:
            return engine
        try:
            engine = sa.create_engine(dsn, pool_pre_ping=True, pool_size=self.pool_size)
        except sa_exc.NoSuchModuleError as exc:  # dialect driver not installed
            raise _SqlFailure(
                AdapterError(
                    ErrorClass.UNAVAILABLE,
                    "sql dialect driver unavailable",
                    retryable=True,
                )
            ) from exc
        except Exception as exc:
            raise _SqlFailure(
                AdapterError(ErrorClass.INVALID, "could not create sql engine")
            ) from exc
        return self._engines.setdefault(dsn, engine)
