"""The worker-primary overlay's REDIS_URL assertion, and the hole it nearly got.

compose.worker-primary.yml declares

    REDIS_URL: ${REDIS_URL:?Worker-primary production requires REDIS_URL}

on both the kernel and the fleet worker, because a worker-primary stack sets
BOLTRIG_PRODUCTION=1 and must not fall back to per-process counters and an
in-process event relay. Every bound would then be per-process and per-boot,
which is the RedisCounter finding all over again.

`make compose-validate` runs `docker compose config` over that overlay, and that
is a SYNTAX check - it could not distinguish "this deployment is missing a
required variable" from "this file is malformed", so it failed on a runner that
had no REDIS_URL exported. The harness now supplies a validation-only value, the
same way it already supplied POSTGRES_PASSWORD.

That fix has an obvious way to go wrong, and this file is here for it: the other
route to a green `config` is to weaken `:?` to `:-`, or drop the line, and
nothing else in the repository would have noticed. So the assertion is pinned
here by reading the file, and the deployment behaviour it stands for is pinned
by running compose with the variable genuinely absent.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
OVERLAY = ROOT / "deploy" / "compose.worker-primary.yml"

# `${VAR:?message}` - the colon matters. ${VAR?message} accepts an EMPTY value,
# and an empty REDIS_URL reaches the counter factory as a falsy string, so the
# process falls back exactly as if the variable were unset.
_REQUIRED = re.compile(r"REDIS_URL:\s*\$\{REDIS_URL:\?[^}]+\}")


@pytest.mark.security
def test_both_production_services_require_redis_url_and_do_not_default_it():
    text = OVERLAY.read_text(encoding="utf-8")
    assert len(_REQUIRED.findall(text)) == 2, (
        "compose.worker-primary.yml must assert REDIS_URL with ${REDIS_URL:?...} on "
        "BOTH kernel and fleet-worker. Found: "
        f"{_REQUIRED.findall(text)}"
    )
    # The failure modes that would still parse, and still be wrong.
    assert "${REDIS_URL:-" not in text, "a default would silence the assertion"
    assert "${REDIS_URL}" not in text, "an unchecked reference would silence it"
    assert "${REDIS_URL?" not in text, "no colon accepts an EMPTY value, which is a fallback"

    # The assertion only means something because the services it guards declare
    # production. If that ever moves, the requirement is guarding nothing.
    assert text.count('BOLTRIG_PRODUCTION: "1"') == 2


@pytest.mark.security
@pytest.mark.skipif(shutil.which("docker") is None, reason="docker is not available")
def test_compose_refuses_the_overlay_when_redis_url_is_genuinely_absent(tmp_path):
    """The behaviour, not the file: `config` must FAIL with REDIS_URL unset.

    This is the negative control for the validation harness. If someone makes
    `make compose-validate` green by weakening the overlay rather than by
    supplying a value, the file test above catches the obvious spellings and
    this catches the rest, because it asks compose itself.

    `--env-file` is not tidiness. Without it, `docker compose` reads the project
    directory's `.env` for interpolation, and a developer machine has one with
    REDIS_URL in it - which is EXACTLY why this failed on a runner while every
    local run was green. A negative control that inherits the ambient
    environment is not a control, so the environment is stated here in full.
    """
    env_file = tmp_path / "env"
    env_file.write_text("POSTGRES_PASSWORD=boltrig-compose-validation-only\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "REDIS_URL"}
    env["BOLTRIG_ENV_FILE"] = ".env.example"
    proc = subprocess.run(
        [
            "docker", "compose",
            "--env-file", str(env_file),
            "-f", "docker-compose.yml",
            "-f", "deploy/compose.dev.yml",
            "-f", "deploy/compose.worker-primary.yml",
            "config", "--quiet",
        ],
        cwd=ROOT, env=env, capture_output=True, text=True,
    )
    assert proc.returncode != 0, (
        "compose ACCEPTED the worker-primary overlay with REDIS_URL unset. The "
        "requirement has been weakened, or the shell exported one."
    )
    assert "REDIS_URL" in proc.stderr


@pytest.mark.security
def test_the_validation_harness_supplies_redis_url_rather_than_removing_the_check():
    """The Makefile line, so the fix cannot be quietly reverted to the failure."""
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    target = makefile.split("compose-validate:", 1)[1]
    worker_line = target.split("compose.worker-primary.yml config", 1)[0]
    assert "REDIS_URL=$(COMPOSE_VALIDATE_REDIS_URL)" in worker_line, (
        "the worker-primary syntax check must supply REDIS_URL, the same way it "
        "supplies POSTGRES_PASSWORD"
    )
    assert "COMPOSE_VALIDATE_REDIS_URL ?=" in makefile
