"""Configuration: process settings and the fleet manifest (S11).

Process settings come from the environment (one per process); the fleet manifest
is per-tenant data that seeds the store. Together they wire a Kernel + fleet for
an organisation without touching core code (P1/P7).
"""

from __future__ import annotations

from .manifest import (
    AdapterConfig,
    BudgetConfig,
    ChatConfig,
    CredentialRef,
    EphemeralRuntime,
    FleetManifest,
    HierarchyConfig,
    HierarchyTier,
    HitlConfig,
    IdentityConfig,
    ModelsConfig,
    NetworkConfig,
    PrivacyConfig,
    SpawnRule,
    apply_manifest,
    export_runtime_environment,
    load_manifest,
)
from .settings import Settings, load_settings

__all__ = [
    "Settings",
    "load_settings",
    "load_manifest",
    "apply_manifest",
    "export_runtime_environment",
    "FleetManifest",
    "IdentityConfig",
    "ModelsConfig",
    "HierarchyConfig",
    "HierarchyTier",
    "EphemeralRuntime",
    "SpawnRule",
    "AdapterConfig",
    "CredentialRef",
    "HitlConfig",
    "NetworkConfig",
    "PrivacyConfig",
    "BudgetConfig",
    "ChatConfig",
]
