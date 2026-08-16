"""One manifest snapshot feeds trusted Codex and Bifrost discovery."""

from __future__ import annotations

import os

import pytest

from boltrig.api.model_runtime_composition import compose_process_model_runtime


class _Manifest:
    def section(self, name: str) -> dict[str, object]:
        if name == "runtimes":
            return {
                "gateway": {
                    "base_url": "http://bifrost:8080/v1",
                    "cache_ttl_seconds": 37,
                }
            }
        return {}


@pytest.mark.invariant("CODEX-COMPOSITION-1")
def test_manifest_gateway_is_exported_before_process_model_resources_are_composed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BOLTRIG_MODEL_GATEWAY_URL", raising=False)
    monkeypatch.delenv("BOLTRIG_MODEL_GATEWAY_TTL", raising=False)
    manifest = _Manifest()
    seen: dict[str, str | None] = {}

    def build_codex_config() -> dict[str, object]:
        seen["gateway"] = os.environ.get("BOLTRIG_MODEL_GATEWAY_URL")
        return {"trusted": True}

    path, loaded, codex_config, catalogue = compose_process_model_runtime(
        find_manifest=lambda: "manifest.yaml",
        load_manifest=lambda _path: manifest,
        build_codex_config=build_codex_config,
    )

    assert path == "manifest.yaml"
    assert loaded is manifest
    assert codex_config == {"trusted": True}
    assert seen == {"gateway": "http://bifrost:8080/v1"}
    assert catalogue._base_url == "http://bifrost:8080/v1"
    assert os.environ["BOLTRIG_MODEL_GATEWAY_TTL"] == "37"
