"""Alembic environment (FR-OPS-01).

Revision 0001 applies an immutable snapshot and subsequent schema changes are
ordered migrations. ``store/schema.sql`` remains the fast first-boot bootstrap;
the migration-parity test compares PostgreSQL catalogues produced by both paths
so the bootstrap cannot drift from Alembic head.

The connection URL is taken from the environment (DATABASE_URL), never
hard-coded. Online migrations use the hash-locked psycopg driver because the
baseline contains a deliberate multi-statement bootstrap that asyncpg prepared
statements cannot execute as one operation.
"""

from __future__ import annotations

import os

from alembic import context

config = context.config


def _database_url() -> str:
    return (
        os.environ.get("DATABASE_URL")
        or os.environ.get("BOLTRIG_DATABASE_URL")
        or os.environ.get("BOLTRIG_TEST_DATABASE_URL")
        or "postgresql://localhost/boltrig"
    )


def _sync_url() -> str:
    url = _database_url()
    if url.startswith("postgres://"):
        url = "postgresql://" + url.removeprefix("postgres://")
    if url.startswith("postgresql+"):
        _scheme, rest = url.split("://", 1)
        return f"postgresql+psycopg://{rest}"
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_sync_url(),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    from sqlalchemy import create_engine

    engine = create_engine(_sync_url(), future=True)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
