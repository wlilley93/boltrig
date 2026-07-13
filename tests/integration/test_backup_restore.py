"""A real pg_dump/pg_restore drill into a fresh PostgreSQL database."""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlsplit, urlunsplit

import asyncpg
import pytest

_PG_CLIENT_IMAGE = (
    "pgvector/pgvector:pg16@"
    "sha256:131dcf7ff6a900545df8e7e092c270aa8c6db2f2c818e408cb45ec21316b74e6"
)


def _dsn_with_database(dsn: str, database: str) -> str:
    parsed = urlsplit(dsn.replace("postgresql+asyncpg://", "postgresql://", 1))
    return urlunsplit((parsed.scheme, parsed.netloc, f"/{database}", parsed.query, ""))


def _pg_command(dsn: str, database: str) -> tuple[list[str], dict[str, str]]:
    parsed = urlsplit(dsn.replace("postgresql+asyncpg://", "postgresql://", 1))
    if not parsed.hostname or not parsed.username:
        raise ValueError("test database URL must include a host and user")
    command = [
        "--host",
        parsed.hostname,
        "--port",
        str(parsed.port or 5432),
        "--username",
        parsed.username,
        "--dbname",
        database,
    ]
    env = dict(os.environ)
    if parsed.password:
        env["PGPASSWORD"] = parsed.password
    sslmode = parse_qs(parsed.query).get("sslmode", [None])[0]
    if sslmode:
        env["PGSSLMODE"] = sslmode
    return command, env


def _run(command: list[str], env: dict[str, str]) -> None:
    completed = subprocess.run(
        command,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=90,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")[-2000:]


def _run_pg_tool(
    tool: str, arguments: list[str], env: dict[str, str], workdir: Path
) -> None:
    env_flags = [
        option
        for name in ("PGPASSWORD", "PGSSLMODE")
        if name in env
        for option in ("--env", name)
    ]
    _run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "host",
            *env_flags,
            "--volume",
            f"{workdir}:/backup",
            _PG_CLIENT_IMAGE,
            tool,
            *arguments,
        ],
        env,
    )


@pytest.mark.invariant("FR-OPS-04")
async def test_backup_restores_into_a_fresh_database(tmp_path: Path) -> None:
    dsn = os.environ.get("BOLTRIG_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("set BOLTRIG_TEST_DATABASE_URL for the backup/restore drill")
    if not shutil.which("docker"):
        pytest.skip("Docker is required for the pinned PostgreSQL restore drill")

    source = urlsplit(dsn.replace("postgresql+asyncpg://", "postgresql://", 1))
    source_db = source.path.lstrip("/")
    target_db = f"boltrig_restore_{uuid.uuid4().hex[:12]}"
    source_dsn = _dsn_with_database(dsn, source_db)
    target_dsn = _dsn_with_database(dsn, target_db)
    source_conn = await asyncpg.connect(source_dsn)
    source_args, source_env = _pg_command(dsn, source_db)
    connection_args = source_args[:-2]
    try:
        await source_conn.execute("DROP TABLE IF EXISTS boltrig_restore_sentinel")
        await source_conn.execute("CREATE TABLE boltrig_restore_sentinel (value TEXT NOT NULL)")
        await source_conn.execute(
            "INSERT INTO boltrig_restore_sentinel (value) VALUES ($1)", "restored"
        )
        _run_pg_tool(
            "createdb",
            [*connection_args, "--maintenance-db", "postgres", target_db],
            source_env,
            tmp_path,
        )
        dump = tmp_path / "boltrig.dump"
        _run_pg_tool(
            "pg_dump",
            [*source_args, "--format=custom", "--file", "/backup/boltrig.dump"],
            source_env,
            tmp_path,
        )
        assert dump.is_file() and dump.stat().st_size > 0
        target_args, target_env = _pg_command(dsn, target_db)
        _run_pg_tool(
            "pg_restore",
            [*target_args, "--no-owner", "--no-privileges", "/backup/boltrig.dump"],
            target_env,
            tmp_path,
        )
        restored = await asyncpg.connect(target_dsn)
        try:
            assert (
                await restored.fetchval("SELECT value FROM boltrig_restore_sentinel") == "restored"
            )
        finally:
            await restored.close()
    finally:
        await source_conn.execute("DROP TABLE IF EXISTS boltrig_restore_sentinel")
        await source_conn.close()
        _run_pg_tool(
            "dropdb",
            [
                *connection_args,
                "--maintenance-db",
                "postgres",
                "--if-exists",
                "--force",
                target_db,
            ],
            source_env,
            tmp_path,
        )
