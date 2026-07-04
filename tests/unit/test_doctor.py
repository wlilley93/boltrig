from __future__ import annotations

from pathlib import Path

from boltrig.api.doctor import load_env_file, run_doctor


MANIFEST = """
organisation: Acme
tenant_id: acme
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


def _secure_env() -> dict[str, str]:
    return {
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
        "BOLTRIG_PI_SIDECAR_URL": "http://pi-sidecar:8090",
        "BOLTRIG_PI_MCP_URL": "http://kernel:8000/v1/mcp",
        "PI_SIDECAR_TOKEN": "p" * 40,
        "PI_SIDECAR_EGRESS_ALLOW": "kernel,bifrost,local-model",
        "BACKUP_REMOTE": "s3:acme/boltrig",
        "BACKUP_PASSPHRASE": "b" * 32,
        "HATCHET_CLIENT_TOKEN": "h" * 24,
    }


def test_production_doctor_has_no_failures_for_secure_posture(tmp_path):
    report = run_doctor(env=_secure_env(), manifest_path=_manifest(tmp_path), production=True)

    assert not report.failed
    assert all(check.status != "fail" for check in report.checks)


def test_production_doctor_flags_deploy_blockers(tmp_path):
    env = {
        "DATABASE_URL": "postgresql+asyncpg://boltrig:CHANGE_ME@postgres:5432/boltrig",
        "POSTGRES_PASSWORD": "",
        "BOLTRIG_DEV_AUTH": "1",
        "BOLTRIG_ALLOWED_HOSTS": "*",
        "PI_SIDECAR_EGRESS_ALLOW": "*",
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
        "pi_egress_allow",
        "backup_remote",
    }.issubset(failures)


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
