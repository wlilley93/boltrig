from __future__ import annotations

from pathlib import Path

import pytest

from boltrig.api.doctor import load_env_file, run_doctor


_REPO = Path(__file__).resolve().parents[2]

# See tests/unit/test_readiness.py for the full reasoning. In short: the legs
# below need a manifest that REQUESTS Codex, and they were reading the
# gitignored `manifest.yaml`. In CI that file does not exist, run_doctor
# swallowed the missing path, and the `next(...)` below then died on an empty
# iterator - five StopIteration errors whose cause was nowhere in the message.
# manifest.example.yaml is the shipped manifest and it requests Codex.
_SHIPPED_MANIFEST = _REPO / "manifest.example.yaml"


MANIFEST = """
organisation: Acme
tenant_id: acme
stack:
  cockpit: boltrig_ui
  coding_agent: codex
identity:
  provider: oidc
models:
  endpoints:
    - id: standard
      kind: openai
      model: gpt-5-mini
      data_class: standard
    - id: local-sensitive
      kind: vllm
      base_url: http://local-model:8000/v1
      model: local
      data_class: sensitive
  default: standard
  sensitive_endpoint: local-sensitive
runtimes:
  gateway:
    base_url: http://bifrost:8080/v1
memory:
  enabled: true
  engine: cognee
  embedding_endpoint: local-sensitive
  extraction_endpoint: local-sensitive
  local_endpoints: [local-sensitive]
  ingest:
    screen_content: true
"""


def _manifest(tmp_path: Path) -> Path:
    path = tmp_path / "manifest.yaml"
    path.write_text(MANIFEST, encoding="utf-8")
    return path


def _browser_manifest(tmp_path: Path) -> Path:
    path = tmp_path / "manifest-browser.yaml"
    text = MANIFEST.replace(
        "  coding_agent: codex\n",
        "  coding_agent: codex\n  browser_automation: browser_cli\n",
    )
    path.write_text(
        text
        + """
adapters:
  - id: browser-cli
    runtime: script
browser_cli:
  enabled: true
""",
        encoding="utf-8",
    )
    return path


def _fake_tool(tmp_path: Path, name: str) -> str:
    path = tmp_path / name
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)
    return str(path)


def _secure_env(tmp_path: Path | None = None) -> dict[str, str]:
    env = {
        "DATABASE_URL": "postgresql+asyncpg://boltrig:secret@db.internal:5432/boltrig?sslmode=require",
        "POSTGRES_PASSWORD": "x" * 36,
        "REDIS_URL": "redis://redis:6379/0",
        "BOLTRIG_AUDIT_HMAC_KEY": "a" * 48,
        "SECRET_STORE": "vault",
        "OIDC_ISSUER": "https://login.acme.test/",
        "OIDC_AUDIENCE": "boltrig",
        "OIDC_JWKS_URI": "https://login.acme.test/jwks",
        "BOLTRIG_ALLOWED_HOSTS": "api.acme.test",
        "BOLTRIG_CORS_ORIGINS": "https://app.acme.test",
        "BOLTRIG_DOMAIN": "boltrig.acme.test",
        "BACKUP_REMOTE": "s3:acme/boltrig",
        "BACKUP_PASSPHRASE": "b" * 32,
        "BACKUP_DATABASES": "boltrig,hatchet",
        "HATCHET_CLIENT_TOKEN": "h" * 24,
    }
    if tmp_path is not None:
        env["PATH"] = ""
    return env


def test_production_doctor_has_no_failures_for_secure_posture(tmp_path):
    report = run_doctor(env=_secure_env(tmp_path), manifest_path=_manifest(tmp_path), production=True)

    assert not report.failed
    assert all(check.status != "fail" for check in report.checks)


@pytest.mark.security
@pytest.mark.invariant("FR-RUN-01")
def test_doctor_reports_a_manifest_still_enabling_the_retired_pi_runtime(tmp_path):
    """A tenant manifest outlives the image that served it.

    The Pi lane was retired under [2026] VJS-PC 20 L1, but a provisioned tenant
    keeps whatever `manifest.yaml` it was given. Measured on the Classical Visas
    tenant on the day of the retirement: `runtimes.pi.enabled: true`, pointing at
    a sidecar that no longer exists. A capability asking for it degrades rather
    than crashing, so this is a WARN and never a deploy blocker - but silence
    would leave the operator no way to find the drift at all.
    """
    path = tmp_path / "manifest-retired.yaml"
    path.write_text(
        MANIFEST.replace(
            "runtimes:\n",
            "runtimes:\n  pi:\n    enabled: true\n",
            1,
        ),
        encoding="utf-8",
    )
    report = run_doctor(env=_secure_env(tmp_path), manifest_path=path, production=True)
    retired = [c for c in report.checks if c.name == "retired_runtime_pi"]
    assert len(retired) == 1
    assert retired[0].status == "warn"
    assert "retired" in retired[0].message
    # a warn, so a tenant carrying the stale block still deploys
    assert not report.failed


@pytest.mark.security
@pytest.mark.invariant("FR-RUN-01")
def test_doctor_stays_silent_on_a_manifest_that_does_not_enable_a_retired_runtime(tmp_path):
    """The check must key on ENABLED, not on the block's presence.

    Without this case the test above passes just as well against a check that
    fires on every manifest, which would train the operator to ignore it.
    """
    path = tmp_path / "manifest-clean.yaml"
    path.write_text(MANIFEST, encoding="utf-8")
    report = run_doctor(env=_secure_env(tmp_path), manifest_path=path, production=True)
    assert not [c for c in report.checks if c.name.startswith("retired_runtime_")]

    disabled = tmp_path / "manifest-disabled.yaml"
    disabled.write_text(
        MANIFEST.replace("runtimes:\n", "runtimes:\n  pi:\n    enabled: false\n", 1),
        encoding="utf-8",
    )
    report = run_doctor(env=_secure_env(tmp_path), manifest_path=disabled, production=True)
    assert not [c for c in report.checks if c.name.startswith("retired_runtime_")]


def test_production_doctor_flags_deploy_blockers(tmp_path):
    env = {
        "PATH": "",
        "DATABASE_URL": "postgresql+asyncpg://boltrig:CHANGE_ME@postgres:5432/boltrig",
        "POSTGRES_PASSWORD": "",
        "BOLTRIG_DEV_AUTH": "1",
        "BOLTRIG_ALLOWED_HOSTS": "*",
    }

    report = run_doctor(env=env, manifest_path=_manifest(tmp_path), production=True)
    failures = {check.name for check in report.checks if check.status == "fail"}

    assert report.failed
    assert {
        "database_url",
        "postgres_password",
        "redis_url",
        "audit_hmac_key",
        "dev_auth",
        "auth_mode",
        "allowed_hosts",
        "backup_remote",
    }.issubset(failures)


@pytest.mark.invariant("FR-HOST-11")
@pytest.mark.parametrize(
    ("browser_home", "browser_bin", "expected"),
    [
        ("/home/will/.config/browser-use", None, {"browser_cli_stack_home"}),
        ("$HOME/.local/share/browser-use", None, {"browser_cli_stack_home"}),
        ("browser-cli-state", None, {"browser_cli_stack_home"}),
        (
            "/var/lib/boltrig/browser-cli",
            "/home/will/.local/bin/browser-use",
            {"browser_cli_stack_cli"},
        ),
        ("/var/lib/boltrig/browser-cli", "missing-browser-use", {"browser_cli_stack_cli"}),
    ],
)
def test_production_doctor_rejects_personal_or_missing_browser_cli(
    tmp_path, browser_home, browser_bin, expected
):
    env = {
        **_secure_env(tmp_path),
        "BOLTRIG_BROWSER_CLI_HOME": browser_home,
        "BOLTRIG_BROWSER_CLI_BIN": browser_bin or _fake_tool(tmp_path, "browser-use"),
    }

    report = run_doctor(env=env, manifest_path=_browser_manifest(tmp_path), production=True)
    failures = {check.name for check in report.checks if check.status == "fail"}

    assert expected.issubset(failures)


def test_load_env_file_merges_simple_dotenv(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        """
        # ignored
        export DATABASE_URL="postgresql://user:pw@postgres/db"
        POSTGRES_PASSWORD='secret-value'
        BAD LINE
        """,
        encoding="utf-8",
    )

    env = load_env_file(env_path, base={"DATABASE_URL": "old", "KEEP": "1"})

    assert env["DATABASE_URL"] == "postgresql://user:pw@postgres/db"
    assert env["POSTGRES_PASSWORD"] == "secret-value"
    assert env["KEEP"] == "1"


@pytest.mark.invariant("SEC-71")
def test_production_doctor_requires_encrypted_recovery_state(tmp_path: Path) -> None:
    env = _secure_env(tmp_path)
    env.pop("BACKUP_PASSPHRASE")

    result = run_doctor(env=env, manifest_path=_manifest(tmp_path), production=True)

    check = next(item for item in result.checks if item.name == "backup_encryption")
    assert check.status == "fail"


@pytest.mark.invariant("SEC-71")
def test_production_doctor_requires_hatchet_in_the_recovery_set(tmp_path: Path) -> None:
    env = _secure_env(tmp_path)
    env["BACKUP_DATABASES"] = "boltrig"

    result = run_doctor(env=env, manifest_path=_manifest(tmp_path), production=True)

    check = next(
        item for item in result.checks if item.name == "backup_hatchet_database"
    )
    assert check.status == "fail"


@pytest.mark.invariant("SEC-71")
def test_production_doctor_requires_the_exact_application_database(
    tmp_path: Path,
) -> None:
    env = _secure_env(tmp_path)
    env["BACKUP_DATABASES"] = "hatchet"

    result = run_doctor(env=env, manifest_path=_manifest(tmp_path), production=True)

    check = next(
        item for item in result.checks if item.name == "backup_application_database"
    )
    assert check.status == "fail"
    assert "omits" in check.message


@pytest.mark.invariant("SEC-71")
def test_production_doctor_uses_the_hatchet_dsn_database_not_a_literal_default(
    tmp_path: Path,
) -> None:
    env = _secure_env(tmp_path)
    env["HATCHET_DATABASE_URL"] = (
        "postgresql://boltrig:secret@db.internal:5432/durable?sslmode=require"
    )

    result = run_doctor(env=env, manifest_path=_manifest(tmp_path), production=True)

    check = next(
        item for item in result.checks if item.name == "backup_hatchet_database"
    )
    assert check.status == "fail"
    assert "omits" in check.message


@pytest.mark.invariant("SEC-71")
def test_production_doctor_accepts_matching_custom_database_names(
    tmp_path: Path,
) -> None:
    env = _secure_env(tmp_path)
    env.update(
        {
            "DATABASE_URL": (
                "postgresql+asyncpg://boltrig:secret@db.internal:5432/app_live"
                "?sslmode=require"
            ),
            "POSTGRES_DB": "app_live",
            "HATCHET_DATABASE_URL": (
                "postgresql://boltrig:secret@db.internal:5432/durable"
                "?sslmode=require"
            ),
            "HATCHET_DATABASE_NAME": "durable",
            "BACKUP_DATABASES": "app_live,durable",
        }
    )

    result = run_doctor(env=env, manifest_path=_manifest(tmp_path), production=True)

    backup_checks = [item for item in result.checks if item.name.startswith("backup_")]
    assert all(item.status != "fail" for item in backup_checks)
    assert next(
        item for item in backup_checks if item.name == "backup_databases"
    ).status == "ok"


@pytest.mark.invariant("SEC-71")
@pytest.mark.parametrize(
    ("updates", "expected_check"),
    [
        ({"POSTGRES_DB": "different"}, "backup_application_database"),
        ({"BACKUP_DATABASES": "boltrig, hatchet"}, "backup_databases"),
        ({"BACKUP_DATABASES": "boltrig,hatchet,hatchet"}, "backup_databases"),
        (
            {"HATCHET_DATABASE_URL": "https://db.internal/hatchet"},
            "backup_hatchet_database",
        ),
    ],
)
def test_production_doctor_fails_closed_on_ambiguous_or_unsafe_database_config(
    tmp_path: Path,
    updates: dict[str, str],
    expected_check: str,
) -> None:
    env = _secure_env(tmp_path)
    env.update(updates)

    result = run_doctor(env=env, manifest_path=_manifest(tmp_path), production=True)

    assert any(
        item.name == expected_check and item.status == "fail"
        for item in result.checks
    )


def test_doctor_refuses_a_codex_runtime_under_production_until_its_gates_open(
    tmp_path: Path,
) -> None:
    path = tmp_path / "manifest-codex.yaml"
    path.write_text(
        MANIFEST
        + """
ephemeral_runtimes:
  - name: codex-worker
    runtime: codex
    model_endpoint: standard
    supported_skills: ["*"]
    max_depth: 1
    cost_tier: standard
""",
        encoding="utf-8",
    )

    production = run_doctor(
        env=_secure_env(tmp_path), manifest_path=path, production=True
    )
    development = run_doctor(
        env=_secure_env(tmp_path), manifest_path=path, production=False
    )

    prod_check = next(c for c in production.checks if c.name == "codex_runtime")
    dev_check = next(c for c in development.checks if c.name == "codex_runtime")
    assert prod_check.status == "fail"
    assert "7 blocker" in prod_check.message
    assert dev_check.status == "warn"


@pytest.mark.security
@pytest.mark.invariant("IAC-005")
def test_core_release_doctor_disables_codex_requested_by_the_shipped_manifest(
    tmp_path: Path,
) -> None:
    env = {**_secure_env(tmp_path), "BOLTRIG_RELEASE_MODE": "core"}

    report = run_doctor(
        env=env,
        manifest_path=_SHIPPED_MANIFEST,
        production=True,
    )

    check = next(item for item in report.checks if item.name == "codex_runtime")
    assert check.status == "ok"
    assert check.message == "Codex is disabled by the exact core release mode."


@pytest.mark.security
@pytest.mark.invariant("IAC-005")
def test_full_release_requires_an_explicit_packaged_desktop_cors_origin(
    tmp_path: Path,
) -> None:
    missing = {
        **_secure_env(tmp_path),
        "BOLTRIG_RELEASE_MODE": "full",
    }
    missing_report = run_doctor(
        env=missing,
        manifest_path=_manifest(tmp_path),
        production=True,
    )
    missing_check = next(
        item for item in missing_report.checks if item.name == "desktop_cors_origin"
    )
    assert missing_check.status == "fail"

    configured = {
        **missing,
        "BOLTRIG_CORS_ORIGINS": "https://app.acme.test,tauri://localhost",
    }
    configured_report = run_doctor(
        env=configured,
        manifest_path=_manifest(tmp_path),
        production=True,
    )
    configured_check = next(
        item for item in configured_report.checks if item.name == "desktop_cors_origin"
    )
    assert configured_check.status == "ok"


@pytest.mark.security
@pytest.mark.invariant("IAC-005")
@pytest.mark.parametrize(
    ("release_mode", "trusted", "message"),
    [
        ("full", None, "development-only"),
        ("CORE", None, "not an exact admitted release mode"),
        ("core ", None, "not an exact admitted release mode"),
        ("core", "1", "conflicts with an enabled trusted Codex lane"),
    ],
)
def test_shipped_manifest_doctor_keeps_non_core_and_conflicting_postures_closed(
    tmp_path: Path,
    release_mode: str,
    trusted: str | None,
    message: str,
) -> None:
    env = {**_secure_env(tmp_path), "BOLTRIG_RELEASE_MODE": release_mode}
    if trusted is not None:
        env["BOLTRIG_CODEX_TRUSTED"] = trusted

    report = run_doctor(
        env=env,
        manifest_path=_SHIPPED_MANIFEST,
        production=True,
    )

    check = next(item for item in report.checks if item.name == "codex_runtime")
    assert check.status == "fail"
    assert message in check.message
