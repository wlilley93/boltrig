"""Deployment-facing ownership and token-recovery contracts for the gateway."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


_REPO = Path(__file__).resolve().parents[2]
_GATEWAY_DIR = str(_REPO / "services" / "channel_gateway")
if _GATEWAY_DIR not in sys.path:
    sys.path.insert(0, _GATEWAY_DIR)

import app as sidecar_app  # noqa: E402


def _clean_gateway_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "CHANNEL_GATEWAY_TOKEN",
        "CHANNEL_GATEWAY_TOKEN_FILE",
        "CHANNEL_GATEWAY_CHANNELS",
        "BOLTRIG_PRODUCTION",
        "BOLTRIG_ENV",
        "ENV",
        "APP_ENV",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("BOLTRIG_KERNEL_URL", "http://localhost:8000")
    monkeypatch.setenv("CHANNEL_GATEWAY_EGRESS_ALLOW", "localhost")


@pytest.mark.security
@pytest.mark.invariant("SEC-177")
async def test_gateway_hot_loads_only_a_changed_valid_token_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clean_gateway_env(monkeypatch)
    token_path = tmp_path / "gateway-token"
    first = "gateway_token_first_aaaaaaaaaaaaaaaa"
    second = "gateway_token_second_bbbbbbbbbbbbbbb"
    token_path.write_text(first, encoding="utf-8")
    monkeypatch.setenv("CHANNEL_GATEWAY_TOKEN_FILE", str(token_path))

    daemon = sidecar_app.build_daemon()
    try:
        assert daemon._token_source == "file"
        assert daemon._token_reloader is not None
        assert daemon._kernel._token_headers() == {
            "x-boltrig-mcp-token": first
        }
        assert daemon._reload_token() is False

        token_path.write_text(second, encoding="utf-8")
        assert daemon._reload_token() is True
        assert daemon._kernel._token_headers() == {
            "x-boltrig-mcp-token": second
        }

        token_path.write_text("malformed token with spaces", encoding="utf-8")
        assert daemon._reload_token() is False
        assert daemon._kernel._token_headers() == {
            "x-boltrig-mcp-token": second
        }
    finally:
        await daemon._kernel.aclose()


@pytest.mark.security
@pytest.mark.invariant("SEC-177")
def test_gateway_refuses_ambiguous_token_sources_and_production_static_specs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clean_gateway_env(monkeypatch)
    token_path = tmp_path / "gateway-token"
    token_path.write_text("gateway_token_file_aaaaaaaaaaaaaaaaa", encoding="utf-8")
    monkeypatch.setenv("CHANNEL_GATEWAY_TOKEN_FILE", str(token_path))
    monkeypatch.setenv(
        "CHANNEL_GATEWAY_TOKEN", "gateway_token_environment_bbbbbbbbbbb"
    )
    with pytest.raises(RuntimeError, match="exactly one gateway token source"):
        sidecar_app.build_daemon()

    monkeypatch.delenv("CHANNEL_GATEWAY_TOKEN_FILE")
    monkeypatch.setenv("BOLTRIG_PRODUCTION", "true")
    monkeypatch.setenv(
        "CHANNEL_GATEWAY_CHANNELS",
        (
            '[{"channel_id":"ch-static","platform":"generic",'
            '"secret":"development-only"}]'
        ),
    )
    with pytest.raises(RuntimeError, match="static channel specs are disabled"):
        sidecar_app.build_daemon()


@pytest.mark.security
@pytest.mark.invariant("SEC-177")
def test_compose_probes_gateway_readiness_and_declares_file_recovery() -> None:
    compose = (_REPO / "docker-compose.yml").read_text(encoding="utf-8")
    gateway = compose.split("\n  channel-gateway:\n", 1)[1].split(
        "\n  signal-cli:\n", 1
    )[0]
    assert "CHANNEL_GATEWAY_TOKEN_FILE:" in gateway
    assert "http://localhost:8091/ready" in gateway
    assert "http://localhost:8091/health" not in gateway
