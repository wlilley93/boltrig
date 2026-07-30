"""Canonical Codex config projection for admitted native-agent limits."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TypedDict

from boltrig.fleet.domain.profile_policy_values import NativeSubagentLimits

from .codex_runtime_config_toml import codex_runtime_features

__all__ = [
    "NativeSubagentLimits",
    "native_receipt_arguments",
    "native_render_arguments",
    "require_native_subagent_limits",
]


def require_native_subagent_limits(value: object, *, receipt: bool = False) -> None:
    if type(value) is not NativeSubagentLimits:
        prefix = "receipt " if receipt else ""
        raise TypeError(f"{prefix}native_subagents must be exact NativeSubagentLimits")


class NativeRenderArguments(TypedDict):
    features: Mapping[str, bool]
    agent_max_threads: int
    agent_max_depth: int


class NativeReceiptArguments(TypedDict):
    native_agents_enabled: bool
    agent_max_threads: int
    agent_max_depth: int


def _native_values(limits: NativeSubagentLimits) -> tuple[bool, int, int]:
    require_native_subagent_limits(limits)
    enabled = limits.max_total > 0
    return (
        enabled,
        limits.max_concurrent if enabled else 1,
        limits.max_depth if enabled else 1,
    )


def native_render_arguments(limits: NativeSubagentLimits) -> NativeRenderArguments:
    enabled, threads, depth = _native_values(limits)
    return {
        "features": codex_runtime_features(native_agents_enabled=enabled),
        "agent_max_threads": threads,
        "agent_max_depth": depth,
    }


def native_receipt_arguments(
    limits: NativeSubagentLimits,
) -> NativeReceiptArguments:
    enabled, threads, depth = _native_values(limits)
    return {
        "native_agents_enabled": enabled,
        "agent_max_threads": threads,
        "agent_max_depth": depth,
    }
