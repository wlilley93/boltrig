"""Alembic environment (FR-OPS-01).

The baseline (0001) applies store/schema.sql verbatim, so the Alembic head and
the hand-maintained schema.sql stay in lock-step: a fresh database brought up
with ``alembic upgrade head`` is byte-identical to one bootstrapped from
schema.sql. Subsequent schema changes are added as ordered revisions.

The connection URL is taken from the environment (DATABASE_URL), never
hard-coded. Alembic needs a *sync* driver, so an ``+asyncpg`` URL is rewritten
to the default sync driver here.
"""

from __future__ import annotations

import os

from alembic import context

config = context.config


def _sync_url() -> str:
    url = (
        os.environ.get("DATABASE_URL")
        or os.environ.get("BOLTRIG_DATABASE_URL")
        or os.environ.get("BOLTRIG_TEST_DATABASE_URL")
        or "postgresql://localhost/boltrig"
    )
    # asyncpg is the app's runtime driver; Alembic runs synchronously.
    return url.replace("+asyncpg", "")


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
    with engine.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
