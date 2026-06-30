"""PostgresStore DSN normalization: accept the SQLAlchemy-style +driver form.

The shipped .env.example uses postgresql+asyncpg://..., but asyncpg only
understands postgresql:// / postgres://. connect() normalizes it; this pins that.
"""

from __future__ import annotations

from boltrig.store.postgres import normalize_dsn


def test_strips_sqlalchemy_driver_suffix():
    assert normalize_dsn("postgresql+asyncpg://u:p@h:5432/db") == "postgresql://u:p@h:5432/db"
    assert normalize_dsn("postgres+psycopg://u:p@h/db") == "postgres://u:p@h/db"


def test_plain_dsn_unchanged():
    assert normalize_dsn("postgresql://u:p@h:5432/db") == "postgresql://u:p@h:5432/db"
    assert normalize_dsn("postgres://h/db") == "postgres://h/db"
