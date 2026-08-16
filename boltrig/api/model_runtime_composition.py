"""Compose one process-owned model runtime snapshot."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from boltrig.config import export_runtime_environment
from boltrig.fleet.bifrost_model_catalogue import BifrostModelCatalogue


def compose_process_model_runtime(
    *,
    find_manifest: Callable[[], str | None],
    load_manifest: Callable[[str], Any],
    build_codex_config: Callable[[], dict[str, object] | None],
) -> tuple[str | None, Any, dict[str, object] | None, BifrostModelCatalogue]:
    """Load one manifest, export its non-secret runtime policy, then snapshot it.

    Explicit process environment remains authoritative because
    ``export_runtime_environment`` only fills missing values.  The trusted Codex
    provider and catalogue are composed after that export, so both see the same
    gateway route for the life of this process.
    """

    manifest_path = find_manifest()
    manifest = load_manifest(manifest_path) if manifest_path else None
    if manifest is not None and callable(getattr(manifest, "section", None)):
        export_runtime_environment(manifest)
    codex_config = build_codex_config()
    return manifest_path, manifest, codex_config, BifrostModelCatalogue()


__all__ = ["compose_process_model_runtime"]
