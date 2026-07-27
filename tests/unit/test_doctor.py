from __future__ import annotations

from pathlib import Path

import pytest

from boltrig.api.doctor import load_env_file, run_doctor


MANIFEST = """
organisation: Acme
tenant_id: acme
stack:
  cockpit: herdr
  coding_agent: opencode
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
  pi:
    enabled: true
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
        "  coding_agent: opencode\n",
        "  coding_agent: opencode\n  browser_automation: browser_cli\n",
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
        "BOLTRIG_HERDR_HOME": "/var/lib/boltrig/herdr",
        "BOLTRIG_OPENCODE_HOME": "/var/lib/boltrig/opencode",
        "BACKUP_REMOTE": "s3:acme/boltrig",
        "BACKUP_PASSPHRASE": "b" * 32,
        "HATCHET_CLIENT_TOKEN": "h" * 24,
    }
    if tmp_path is not None:
        env["PATH"] = ""
        env["HERDR_BIN"] = _fake_tool(tmp_path, "herdr")
        env["BOLTRIG_OPENCODE_BIN"] = _fake_tool(tmp_path, "opencode")
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
    report = run_doctor(env=_secure_env(tmp_path), manifest_path=_manifest(tmp_path), production=True)
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
    path.write_text(MANIFEST.replace("  pi:\n    enabled: true\n", ""), encoding="utf-8")
    report = run_doctor(env=_secure_env(tmp_path), manifest_path=path, production=True)
    assert not [c for c in report.checks if c.name.startswith("retired_runtime_")]

    disabled = tmp_path / "manifest-disabled.yaml"
    disabled.write_text(
        MANIFEST.replace("  pi:\n    enabled: true\n", "  pi:\n    enabled: false\n"),
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
        "herdr_stack_home",
        "herdr_stack_cli",
        "opencode_stack_home",
        "opencode_stack_cli",
        "backup_remote",
    }.issubset(failures)


@pytest.mark.invariant("FR-HOST-09")
@pytest.mark.invariant("FR-RUN-17")
@pytest.mark.parametrize(
    ("herdr_home", "opencode_home", "expected"),
    [
        ("/home/will/.config/herdr", "/var/lib/boltrig/opencode", {"herdr_stack_home"}),
        ("/var/lib/boltrig/herdr", "/Users/will/.opencode", {"opencode_stack_home"}),
        ("$HOME/.config/herdr", "/var/lib/boltrig/opencode", {"herdr_stack_home"}),
        ("/root/.local/share/herdr", "/var/lib/boltrig/opencode", {"herdr_stack_home"}),
        ("/home/dev/herdr", "/var/lib/boltrig/opencode", {"herdr_stack_home"}),
        ("/var/lib/boltrig/herdr", ".opencode", {"opencode_stack_home"}),
        (
            "/var/lib/boltrig/agent-state",
            "/var/lib/boltrig/agent-state",
            {"stack_tool_home_collision"},
        ),
    ],
)
def test_production_doctor_rejects_personal_herdr_opencode_state(
    tmp_path, herdr_home, opencode_home, expected
):
    env = {
        **_secure_env(tmp_path),
        "BOLTRIG_HERDR_HOME": herdr_home,
        "BOLTRIG_OPENCODE_HOME": opencode_home,
    }

    report = run_doctor(env=env, manifest_path=_manifest(tmp_path), production=True)
    failures = {check.name for check in report.checks if check.status == "fail"}

    assert expected.issubset(failures)


@pytest.mark.invariant("FR-HOST-10")
@pytest.mark.invariant("FR-RUN-18")
@pytest.mark.parametrize(
    ("herdr_bin", "opencode_bin", "expected"),
    [
        ("/home/will/.local/bin/herdr", None, {"herdr_stack_cli"}),
        (None, "/Users/will/.opencode/bin/opencode", {"opencode_stack_cli"}),
        ("/does/not/exist/herdr", None, {"herdr_stack_cli"}),
        (None, "not-on-path-opencode", {"opencode_stack_cli"}),
        ("relative/herdr", None, {"herdr_stack_cli"}),
    ],
)
def test_production_doctor_rejects_missing_or_personal_herdr_opencode_bins(
    tmp_path, herdr_bin, opencode_bin, expected
):
    env = _secure_env(tmp_path)
    if herdr_bin is not None:
        env["HERDR_BIN"] = herdr_bin
    if opencode_bin is not None:
        env["BOLTRIG_OPENCODE_BIN"] = opencode_bin

    report = run_doctor(env=env, manifest_path=_manifest(tmp_path), production=True)
    failures = {check.name for check in report.checks if check.status == "fail"}

    assert expected.issubset(failures)


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
