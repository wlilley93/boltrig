"""Disabled-by-default, secretless config composition for Codex 0.144.3."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Never, SupportsIndex

from .codex_runtime_config_argv import (
    CODEX_APP_SERVER_BASE_ARGUMENTS,
    codex_app_server_arguments,
    validate_app_server_arguments,
)
from .codex_runtime_config_toml import (
    CODEX_MODEL_PROVIDER_ID,
    CODEX_RUNTIME_DISABLED_FEATURES,
    CODEX_RUNTIME_PROVIDER_CONTRACT_DIGEST,
    _render_codex_runtime_config,
    _runtime_config_skill_entries,
    canonical_skill_entries_digest,
    runtime_config_matches_receipt,
)
from .codex_runtime_config_policy import (
    CodexRuntimeConfigError,
    validate_cell_id,
    validate_cell_paths,
    validate_ingress_socket_name,
    validate_digest,
    validate_model_id,
    validate_receipt_paths,
    validated_runtime_skill_entries,
    validated_skill_fragment,
)

CODEX_RUNTIME_CONFIG_VERSION = 1
CODEX_RUNTIME_CLI_VERSION = "0.144.3"
CODEX_RUNTIME_CONFIG_PRODUCTION_READY = False
CODEX_RUNTIME_INITIALIZE_EXPERIMENTAL_API = False
MAX_CODEX_RUNTIME_CONFIG_BYTES = 768 * 1024


class CodexReasoningEffort(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"


class CodexRuntimeSurface(str, Enum):
    AGENTS = "agents"
    APPS = "apps"
    HOOKS = "hooks"
    PLUGINS = "plugins"


@dataclass(frozen=True, order=True)
class CodexRuntimeSurfaceAttestation:
    surface: CodexRuntimeSurface
    inventory_digest: str

    def __post_init__(self) -> None:
        if type(self.surface) is not CodexRuntimeSurface:
            raise TypeError("surface must be an exact CodexRuntimeSurface")
        validate_digest("surface inventory digest", self.inventory_digest)


def _surface_attestations(
    value: object,
) -> tuple[CodexRuntimeSurfaceAttestation, ...]:
    if type(value) is not tuple or any(
        type(item) is not CodexRuntimeSurfaceAttestation for item in value
    ):
        raise CodexRuntimeConfigError("surface attestations must be an exact tuple")
    ordered = tuple(sorted(value, key=lambda item: item.surface.value))
    if len(ordered) > len(CodexRuntimeSurface) or len({item.surface for item in ordered}) != len(
        ordered
    ):
        raise CodexRuntimeConfigError("surface attestations must be unique and bounded")
    if ordered:
        raise CodexRuntimeConfigError(
            "surface attestations require a governed verifier and are disabled"
        )
    return ordered


@dataclass(frozen=True, repr=False, slots=True)
class CodexRuntimeConfigRequest:
    cell_id: str
    cell_root: Path
    codex_home: Path
    helper_path: Path
    helper_sha256: str
    socket_name: str
    model_id: str
    model_policy_digest: str
    reasoning_effort: CodexReasoningEffort
    proxy_port: int
    skill_config_fragment: bytes
    skill_inventory_digest: str
    surface_attestations: tuple[CodexRuntimeSurfaceAttestation, ...] = ()

    def __post_init__(self) -> None:
        _validate_request(self)

    def __repr__(self) -> str:
        return "CodexRuntimeConfigRequest(redacted=True)"

    def __reduce_ex__(self, _protocol: SupportsIndex) -> Never:
        raise TypeError("runtime config requests must not be pickled or copied")


def _validate_request(request: CodexRuntimeConfigRequest) -> None:
    validate_cell_id(request.cell_id)
    validate_cell_paths(request.cell_root, request.codex_home, request.helper_path)
    validate_digest("model auth helper digest", request.helper_sha256)
    validate_ingress_socket_name(request.socket_name)
    validate_model_id(request.model_id)
    validate_digest("model policy digest", request.model_policy_digest)
    if type(request.reasoning_effort) is not CodexReasoningEffort:
        raise TypeError("reasoning_effort must be an exact CodexReasoningEffort")
    if type(request.proxy_port) is not int or not 1 <= request.proxy_port <= 65535:
        raise CodexRuntimeConfigError("proxy port must be between 1 and 65535")
    validate_digest("skill inventory digest", request.skill_inventory_digest)
    _surface_attestations(request.surface_attestations)


def _snapshot_request(
    request: CodexRuntimeConfigRequest,
) -> CodexRuntimeConfigRequest:
    """Copy caller-owned state into one private, revalidated value object."""

    return CodexRuntimeConfigRequest(
        cell_id=request.cell_id,
        cell_root=request.cell_root,
        codex_home=request.codex_home,
        helper_path=request.helper_path,
        helper_sha256=request.helper_sha256,
        socket_name=request.socket_name,
        model_id=request.model_id,
        model_policy_digest=request.model_policy_digest,
        reasoning_effort=request.reasoning_effort,
        proxy_port=request.proxy_port,
        skill_config_fragment=request.skill_config_fragment,
        skill_inventory_digest=request.skill_inventory_digest,
        surface_attestations=request.surface_attestations,
    )


@dataclass(frozen=True, repr=False, slots=True)
class CodexRuntimeConfigReceipt:
    """Composition metadata; external evidence needs trusted durable verification."""
    config_digest: str
    config_bytes: int
    cell_id: str
    cell_root: str
    codex_home: str
    model_id: str
    model_policy_digest: str
    helper_path: str
    helper_sha256: str
    socket_name: str
    reasoning_effort: CodexReasoningEffort
    proxy_port: int
    skill_entries_digest: str
    skill_inventory_digest: str
    surface_attestations: tuple[CodexRuntimeSurfaceAttestation, ...]
    config_version: int = CODEX_RUNTIME_CONFIG_VERSION
    codex_cli_version: str = CODEX_RUNTIME_CLI_VERSION
    provider_id: str = CODEX_MODEL_PROVIDER_ID
    provider_contract_digest: str = CODEX_RUNTIME_PROVIDER_CONTRACT_DIGEST
    initialize_experimental_api: bool = CODEX_RUNTIME_INITIALIZE_EXPERIMENTAL_API
    production_ready: bool = CODEX_RUNTIME_CONFIG_PRODUCTION_READY

    def __post_init__(self) -> None:
        _validate_receipt(self)

    @property
    def app_server_arguments(self) -> tuple[str, ...]:
        """Derive the H5-pinned App Server argv from this receipt's own fields.

        Deliberately NOT a stored field. A stored copy would have to be validated
        beside the record it duplicates, and the two could then drift apart; the
        argv is a function of the record, so it is computed from the record. A
        forged value is not merely rejected, it is not expressible: there is no
        slot to write and no setter to call.
        """

        return codex_app_server_arguments(
            cell_id=self.cell_id,
            helper_path=self.helper_path,
            socket_name=self.socket_name,
            proxy_port=self.proxy_port,
            features=CODEX_RUNTIME_DISABLED_FEATURES,
        )

    def matches(self, config_toml: str) -> bool:
        if type(config_toml) is not str:
            return False
        try:
            encoded = config_toml.encode("utf-8", errors="strict")
        except UnicodeError:
            return False
        actual = "sha256:" + hashlib.sha256(encoded).hexdigest()
        return len(encoded) == self.config_bytes and hmac.compare_digest(actual, self.config_digest)

    def __repr__(self) -> str:
        return "CodexRuntimeConfigReceipt(redacted=True, production_ready=False)"


def _validate_receipt(receipt: CodexRuntimeConfigReceipt) -> None:
    validate_digest("config digest", receipt.config_digest)
    if (
        type(receipt.config_bytes) is not int
        or not 1 <= receipt.config_bytes <= MAX_CODEX_RUNTIME_CONFIG_BYTES
    ):
        raise CodexRuntimeConfigError("config byte count is invalid")
    validate_cell_id(receipt.cell_id)
    validate_receipt_paths(receipt.cell_root, receipt.codex_home, receipt.helper_path)
    # The receipt's socket name was previously covered only by the re-render
    # comparison. Check it in its own right: it names the endpoint the App Server's
    # helper will connect to, so it is worth the same standing as the other paths.
    validate_ingress_socket_name(receipt.socket_name)
    # Derived from the record, so it cannot disagree with it. Checked anyway so a
    # broken derivation fails at composition rather than at execve.
    validate_app_server_arguments(receipt.app_server_arguments, cell_id=receipt.cell_id)
    validate_model_id(receipt.model_id)
    validate_digest("model policy digest", receipt.model_policy_digest)
    if type(receipt.reasoning_effort) is not CodexReasoningEffort:
        raise TypeError("receipt reasoning_effort must be an exact CodexReasoningEffort")
    if type(receipt.proxy_port) is not int or not 1 <= receipt.proxy_port <= 65535:
        raise CodexRuntimeConfigError("receipt proxy port must be between 1 and 65535")
    validate_digest("model auth helper digest", receipt.helper_sha256)
    validate_digest("skill entries digest", receipt.skill_entries_digest)
    validate_digest("skill inventory digest", receipt.skill_inventory_digest)
    if receipt.surface_attestations != _surface_attestations(receipt.surface_attestations):
        raise CodexRuntimeConfigError("receipt surface attestations are not canonical")
    exact = (
        type(receipt.config_version) is int
        and receipt.config_version == CODEX_RUNTIME_CONFIG_VERSION
        and type(receipt.codex_cli_version) is str
        and receipt.codex_cli_version == CODEX_RUNTIME_CLI_VERSION
        and type(receipt.provider_id) is str
        and receipt.provider_id == CODEX_MODEL_PROVIDER_ID
        and type(receipt.provider_contract_digest) is str
        and receipt.provider_contract_digest == CODEX_RUNTIME_PROVIDER_CONTRACT_DIGEST
        and receipt.initialize_experimental_api is False
        and receipt.production_ready is False
    )
    if not exact:
        raise CodexRuntimeConfigError("runtime config receipt contract is invalid")


@dataclass(frozen=True, repr=False, slots=True)
class ComposedCodexRuntimeConfig:
    config_toml: str
    receipt: CodexRuntimeConfigReceipt

    def __post_init__(self) -> None:
        if type(self.config_toml) is not str or type(self.receipt) is not CodexRuntimeConfigReceipt:
            raise TypeError("composed config values must use exact runtime config types")
        _validate_receipt(self.receipt)
        try:
            encoded = self.config_toml.encode("ascii", errors="strict")
        except UnicodeError:
            raise CodexRuntimeConfigError("runtime config must be ASCII") from None
        if not 1 <= len(encoded) <= MAX_CODEX_RUNTIME_CONFIG_BYTES:
            raise CodexRuntimeConfigError("runtime config exceeds its byte bound")
        if not self.receipt.matches(self.config_toml):
            raise CodexRuntimeConfigError("runtime config does not match its receipt")
        parsed_entries = _runtime_config_skill_entries(self.config_toml)
        if parsed_entries is None:
            raise CodexRuntimeConfigError("runtime config and receipt metadata are inconsistent")
        try:
            skill_entries = validated_runtime_skill_entries(
                parsed_entries, Path(self.receipt.codex_home)
            )
        except CodexRuntimeConfigError:
            raise CodexRuntimeConfigError(
                "runtime config skill policy is inconsistent with its receipt"
            ) from None
        if not runtime_config_matches_receipt(
            self.config_toml,
            model_id=self.receipt.model_id,
            reasoning_effort=self.receipt.reasoning_effort.value,
            cell_id=self.receipt.cell_id,
            helper_path=self.receipt.helper_path,
            socket_name=self.receipt.socket_name,
            proxy_port=self.receipt.proxy_port,
            provider_id=self.receipt.provider_id,
            skill_entries=skill_entries,
            skill_entries_digest=self.receipt.skill_entries_digest,
        ):
            raise CodexRuntimeConfigError("runtime config and receipt metadata are inconsistent")

    def __repr__(self) -> str:
        return "ComposedCodexRuntimeConfig(redacted=True, production_ready=False)"


def compose_codex_runtime_config(
    request: CodexRuntimeConfigRequest,
    *,
    ambient_overrides: Mapping[str, object] | None = None,
) -> ComposedCodexRuntimeConfig:
    """Compose a complete config without reading ambient state or accepting overrides."""

    if type(request) is not CodexRuntimeConfigRequest:
        raise TypeError("request must be an exact CodexRuntimeConfigRequest")
    snapshot = _snapshot_request(request)
    if ambient_overrides is not None:
        if not isinstance(ambient_overrides, Mapping):
            raise TypeError("ambient_overrides must be a mapping or None")
        if ambient_overrides:
            raise CodexRuntimeConfigError("ambient runtime config overrides are forbidden")
    attestations = _surface_attestations(snapshot.surface_attestations)
    entries = validated_skill_fragment(
        snapshot.skill_config_fragment, snapshot.codex_home
    )
    config_toml = _render_codex_runtime_config(
        model_id=snapshot.model_id,
        reasoning_effort=snapshot.reasoning_effort.value,
        cell_id=snapshot.cell_id,
        helper_path=snapshot.helper_path.as_posix(),
        socket_name=snapshot.socket_name,
        proxy_port=snapshot.proxy_port,
        features=CODEX_RUNTIME_DISABLED_FEATURES,
        skill_entries=entries,
    )
    encoded = config_toml.encode("ascii", errors="strict")
    if len(encoded) > MAX_CODEX_RUNTIME_CONFIG_BYTES:
        raise CodexRuntimeConfigError("runtime config exceeds its byte bound")
    receipt = CodexRuntimeConfigReceipt(
        config_digest="sha256:" + hashlib.sha256(encoded).hexdigest(),
        config_bytes=len(encoded),
        cell_id=snapshot.cell_id,
        cell_root=snapshot.cell_root.as_posix(),
        codex_home=snapshot.codex_home.as_posix(),
        model_id=snapshot.model_id,
        model_policy_digest=snapshot.model_policy_digest,
        helper_path=snapshot.helper_path.as_posix(),
        helper_sha256=snapshot.helper_sha256,
        socket_name=snapshot.socket_name,
        reasoning_effort=snapshot.reasoning_effort,
        proxy_port=snapshot.proxy_port,
        skill_entries_digest=canonical_skill_entries_digest(entries),
        skill_inventory_digest=snapshot.skill_inventory_digest,
        surface_attestations=attestations,
    )
    return ComposedCodexRuntimeConfig(config_toml, receipt)


__all__ = [
    "CODEX_APP_SERVER_BASE_ARGUMENTS",
    "CODEX_RUNTIME_CLI_VERSION",
    "CODEX_RUNTIME_CONFIG_PRODUCTION_READY",
    "CODEX_RUNTIME_CONFIG_VERSION",
    "CODEX_RUNTIME_INITIALIZE_EXPERIMENTAL_API",
    "CODEX_RUNTIME_PROVIDER_CONTRACT_DIGEST",
    "CodexReasoningEffort",
    "CodexRuntimeConfigError",
    "CodexRuntimeConfigReceipt",
    "CodexRuntimeConfigRequest",
    "CodexRuntimeSurface",
    "CodexRuntimeSurfaceAttestation",
    "ComposedCodexRuntimeConfig",
    "compose_codex_runtime_config",
]
