"""A real pg_dump/pg_restore drill into a fresh PostgreSQL database."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import parse_qs, urlsplit, urlunsplit

import asyncpg
import pytest

_REPO = Path(__file__).resolve().parents[2]
_BACKUP_DOCKERFILE = _REPO / "deploy" / "backup.Dockerfile"


def _shipped_pg_client_image() -> str:
    """The base image `deploy/backup.Dockerfile` actually ships, read from it.

    DERIVED, not restated. This module named its own
    `pgvector/pgvector:pg16@sha256:...` literal, so the drill exercised a client
    that had no connection to the one in production. The consequence is precise:
    dependabot #4 proposes moving the backup image from postgres 16 to 18, and its
    green run would have told us nothing at all, because the drill would have gone
    on dumping and restoring with a pg16 client either way. A drill that cannot
    detect the change it is meant to gate is a drill in name only.

    The Dockerfile's first FROM is the base the backup tools come from, and it is
    digest-pinned there (IAC-002), so this carries the pin without duplicating it.
    """
    for line in _BACKUP_DOCKERFILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("FROM "):
            return stripped.split()[1]
    raise AssertionError(f"no FROM line in {_BACKUP_DOCKERFILE}")


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
            _shipped_pg_client_image(),
            tool,
            *arguments,
        ],
        env,
    )


@pytest.fixture
def docker_shared_workdir() -> Iterator[Path]:
    # Docker Desktop/Colima may not share the platform's default pytest temp
    # root with its VM. The checkout's parent is already a required bind source,
    # and a test-local directory keeps that transport detail out of other tests.
    with tempfile.TemporaryDirectory(
        prefix="boltrig-backup-restore-", dir=_REPO.parent
    ) as directory:
        yield Path(directory)


@pytest.mark.invariant("FR-OPS-04")
async def test_backup_restores_into_a_fresh_database(
    docker_shared_workdir: Path,
) -> None:
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
            docker_shared_workdir,
        )
        dump = docker_shared_workdir / "boltrig.dump"
        _run_pg_tool(
            "pg_dump",
            [*source_args, "--format=custom", "--file", "/backup/boltrig.dump"],
            source_env,
            docker_shared_workdir,
        )
        assert dump.is_file() and dump.stat().st_size > 0
        target_args, target_env = _pg_command(dsn, target_db)
        _run_pg_tool(
            "pg_restore",
            [*target_args, "--no-owner", "--no-privileges", "/backup/boltrig.dump"],
            target_env,
            docker_shared_workdir,
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
            docker_shared_workdir,
        )
