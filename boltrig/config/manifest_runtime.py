"""Secret-free process environment projection for a fleet manifest."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

from .environment import is_truthy

if TYPE_CHECKING:
    from .manifest import FleetManifest


def export_runtime_environment(
    manifest: FleetManifest, env: dict[str, str] | None = None
) -> None:
    """Export config-only runtime seams while preserving explicit env values."""
    target = env if env is not None else os.environ
    runtimes = manifest.section("runtimes")
    gateway = runtimes.get("gateway") if isinstance(runtimes.get("gateway"), dict) else {}
    if not isinstance(gateway, dict):
        return
    base_url = str(gateway.get("base_url") or "").strip()
    if base_url and "BOLTRIG_MODEL_GATEWAY_URL" not in target:
        target["BOLTRIG_MODEL_GATEWAY_URL"] = base_url
    ttl = gateway.get("cache_ttl_seconds")
    if ttl not in (None, "") and "BOLTRIG_MODEL_GATEWAY_TTL" not in target:
        try:
            target["BOLTRIG_MODEL_GATEWAY_TTL"] = str(int(ttl))
        except (TypeError, ValueError):
            pass
    health = gateway.get("health") if isinstance(gateway.get("health"), dict) else {}
    if isinstance(health, dict):
        enabled = health.get("enabled")
        if enabled not in (None, "") and "BOLTRIG_MODEL_GATEWAY_HEALTH" not in target:
            target["BOLTRIG_MODEL_GATEWAY_HEALTH"] = "1" if is_truthy(str(enabled)) else "0"
        path = str(health.get("path") or "").strip()
        if path and "BOLTRIG_MODEL_GATEWAY_HEALTH_PATH" not in target:
            target["BOLTRIG_MODEL_GATEWAY_HEALTH_PATH"] = path
        timeout = health.get("timeout")
        if timeout not in (None, "") and "BOLTRIG_MODEL_GATEWAY_HEALTH_TIMEOUT" not in target:
            target["BOLTRIG_MODEL_GATEWAY_HEALTH_TIMEOUT"] = str(timeout)
    profiles = gateway.get("model_profiles")
    if isinstance(profiles, dict) and profiles and "BOLTRIG_MODEL_PROFILES" not in target:
        target["BOLTRIG_MODEL_PROFILES"] = json.dumps(profiles, sort_keys=True)
    browser = manifest.section("browser_cli")
    policy = str(browser.get("cloud_policy") or "").strip().lower()
    if policy and "BOLTRIG_BROWSER_CLOUD_POLICY" not in target:
        target["BOLTRIG_BROWSER_CLOUD_POLICY"] = policy
