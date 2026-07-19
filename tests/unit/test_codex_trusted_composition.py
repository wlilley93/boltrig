"""Tests for the trusted read-only Codex composition root ([2026] VJS-CC-VJS 2).

``build_trusted_codex_config`` is the api-layer factory that assembles the heavy
``TrustedProxyCodexPhaseCellProvider`` (which imports the fleet infrastructure
layer) and injects it down into ``RuntimeResolver``. These pin the off-by-default
no-op (missing flag / binary / stack root => ``None``, constructs nothing) and the
on path (all three set => a real provider in the expected dict shape). No live
Codex turn runs here; the factory only CONSTRUCTS.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from boltrig.api.codex_trusted import build_trusted_codex_config
from boltrig.config.settings import Settings
from boltrig.fleet.infrastructure.codex_trusted_proxy_provider import (
    TrustedProxyCodexPhaseCellProvider,
)

# Any real file that is absolute; the supervisor only records the path at
# construction (binary existence/pinning is verified later, at cell start).
_REAL_BINARY = "/bin/sh"


def _settings(**overrides: object) -> Settings:
    return Settings(**overrides)  # type: ignore[arg-type]


def test_returns_none_when_codex_trusted_off(tmp_path: Path) -> None:
    settings = _settings(
        codex_trusted=False,
        codex_binary=_REAL_BINARY,
        codex_stack_root=str(tmp_path),
    )
    result = build_trusted_codex_config(
        settings, model_id="glm-4.6", gateway_base_url="http://gateway"
    )
    assert result is None


def test_returns_none_when_binary_missing(tmp_path: Path) -> None:
    settings = _settings(
        codex_trusted=True,
        codex_binary=None,
        codex_stack_root=str(tmp_path),
    )
    assert (
        build_trusted_codex_config(
            settings, model_id="glm-4.6", gateway_base_url="http://gateway"
        )
        is None
    )


def test_returns_none_when_stack_root_missing() -> None:
    settings = _settings(
        codex_trusted=True,
        codex_binary=_REAL_BINARY,
        codex_stack_root=None,
    )
    assert (
        build_trusted_codex_config(
            settings, model_id="glm-4.6", gateway_base_url="http://gateway"
        )
        is None
    )


def test_builds_provider_when_all_three_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The image bakes the shared helper at /opt/boltrig/codex/model_auth_helper,
    # which does not exist on a dev host; /bin/sh has the same proved shape
    # (root-owned, unwritable chain) so the boundary assertion is real, not stubbed.
    monkeypatch.setenv("BOLTRIG_CODEX_AUTH_HELPER", os.path.realpath("/bin/sh"))
    settings = _settings(
        codex_trusted=True,
        codex_binary=_REAL_BINARY,
        codex_stack_root=str(tmp_path),
        model_gateway_key="k",
    )
    result = build_trusted_codex_config(
        settings, model_id="glm-4.6", gateway_base_url="http://gateway"
    )
    assert result is not None
    assert result["trusted"] is True
    assert result["stack_root"] == tmp_path
    assert isinstance(result["provider"], TrustedProxyCodexPhaseCellProvider)
    # Close the httpx client the provider opened so the test leaves nothing running.
    import asyncio

    asyncio.run(result["provider"]._client.aclose())
