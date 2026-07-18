"""Resolve model endpoints and build runtimes for ephemeral spawns."""

from __future__ import annotations

import os
from dataclasses import replace
from typing import Any, cast

from boltrig.config.environment import production_signal
from boltrig.models import AgentCapability, CredentialResolution, InvocationContext, ModelEndpoint

from .model_gateway import ModelGateway, apply_gateway, gateway_config
from .model_profiles import apply_model_profile, select_model_profile
from .model_router import select_model_endpoint
from .runtime import Runtime, build_runtime, runtime_for_provider


def _routed_endpoint(tenant_id: str, base: ModelEndpoint | None, resolution: Any) -> ModelEndpoint:
    """Apply an AI-config provider/model/base-url selection to an endpoint."""
    model = resolution.model or (base.model if base is not None else "")
    base_url = resolution.base_url or (base.base_url if base is not None else None)
    if base is not None:
        return replace(base, model=model, base_url=base_url)
    return ModelEndpoint(
        id="ai-config",
        tenant_id=tenant_id,
        kind=(resolution.provider or "openai"),
        model=model,
        base_url=base_url,
        data_class="standard",
    )


class RuntimeResolver:
    """Owns runtime routing while leaving spawn orchestration thin."""

    def __init__(
        self,
        kernel: Any,
        *,
        sensitive_endpoint_id: str | None = None,
        codex_config: dict[str, Any] | None = None,
    ) -> None:
        self._kernel = kernel
        self._sensitive_endpoint_id = sensitive_endpoint_id
        # Trusted read-only Codex provider config, injected from the api composition
        # root ([2026] VJS-CC-VJS 2). None (the default) => the codex runtime degrades
        # to ScriptRuntime exactly as before (off by default = total no-op).
        self._codex = codex_config
        self._pi = {
            "sidecar_url": os.environ.get("BOLTRIG_PI_SIDECAR_URL") or None,
            "mcp_url": os.environ.get("BOLTRIG_PI_MCP_URL", "http://kernel:8000/v1/mcp"),
            "max_steps": int(os.environ.get("BOLTRIG_PI_MAX_STEPS", "12")),
        }
        self._rivet = {
            "agentos_url": os.environ.get("RIVET_AGENTOS_URL")
            or os.environ.get("BOLTRIG_RIVET_AGENTOS_URL")
            or None,
            "mcp_url": os.environ.get("BOLTRIG_RIVET_MCP_URL")
            or os.environ.get("BOLTRIG_MCP_URL")
            or os.environ.get("BOLTRIG_PI_MCP_URL", "http://kernel:8000/v1/mcp"),
            "run_path": os.environ.get("RIVET_AGENTOS_RUN_PATH", "/runs"),
        }
        self._gateway = gateway_config()
        self._bindings = ModelGateway(ttl_seconds=int(cast(int, self._gateway["ttl_seconds"])))

    async def runtime_for(
        self,
        tenant_id: str,
        capability: AgentCapability,
        context: InvocationContext | None = None,
    ) -> Runtime:
        sensitive = bool(context is not None and context.extra.get("data_class") == "sensitive")
        endpoint = await select_model_endpoint(
            self._kernel.store,
            tenant_id,
            capability.model_endpoint,
            sensitive=sensitive,
            sensitive_endpoint_id=self._sensitive_endpoint_id,
            audit=self._kernel.audit,
            actor=capability.name,
        )
        api_key, resolution = await self._resolve_ai_key(tenant_id, context)
        runtime_override: str | None = None
        model_route: dict[str, str] | None = None

        if resolution is not None and not resolution.is_default and not sensitive:
            runtime_override = runtime_for_provider(resolution.provider)
            if runtime_override is not None:
                endpoint = _routed_endpoint(tenant_id, endpoint, resolution)

        if context is not None and not sensitive:
            profile = select_model_profile(dict(context.extra or {}))
            endpoint, profile_runtime, profile_route = apply_model_profile(
                endpoint, profile, tenant_id=tenant_id
            )
            if profile_runtime is not None:
                runtime_override = profile_runtime
            if profile_route is not None:
                model_route = profile_route.audit_detail()

        conversation_id = context.extra.get("conversation_id") if context is not None else None
        endpoint = apply_gateway(
            endpoint,
            gateway_url=cast(str | None, self._gateway["base_url"]),
            binding=self._bindings,
            conversation_id=conversation_id,
            sensitive=sensitive,
        )

        def lookup(endpoint_id: str) -> ModelEndpoint | None:
            if endpoint is not None and endpoint.id == endpoint_id:
                return endpoint
            return None

        endpoint_override = endpoint if runtime_override is not None else None
        runtime = build_runtime(
            capability,
            lookup,
            pi_config=self._pi_config(context) if capability.runtime == "pi" else None,
            opencode_config=self._opencode_config(capability, runtime_override),
            rivet_config=self._rivet_config(capability, runtime_override),
            codex_config=self._codex_config(capability, runtime_override),
            api_key=api_key,
            runtime_override=runtime_override,
            endpoint_override=endpoint_override,
        )
        if model_route:
            setattr(runtime, "model_route", model_route)
        return runtime

    async def _resolve_ai_key(
        self, tenant_id: str, context: InvocationContext | None
    ) -> tuple[str | None, Any | None]:
        production = production_signal() is not None
        if context is None:
            if production:
                raise CredentialResolution(
                    "production runtime requires an authenticated execution context"
                )
            return None, None
        from boltrig.identity import load_ai_key_material, resolve_ai_key

        try:
            resolution = await resolve_ai_key(
                self._kernel.store,
                tenant_id,
                workspace_id=context.workspace_id,
                user_id=context.on_behalf_of,
            )
            material = await load_ai_key_material(self._kernel.store, tenant_id, resolution)
        except Exception as exc:
            if production:
                raise CredentialResolution(
                    "production AI credential resolution is unavailable"
                ) from exc
            return None, None
        if resolution.credential_ref is not None and not material:
            raise CredentialResolution("configured AI credential material is unavailable")
        if resolution.is_default and production:
            raise CredentialResolution(
                "production AI execution requires a scoped credential reference"
            )
        return material, resolution

    def _pi_config(self, context: InvocationContext | None) -> dict[str, Any]:
        cfg: dict[str, Any] = {
            "sidecar_url": self._pi["sidecar_url"],
            "mcp_url": self._pi["mcp_url"],
            "max_steps": self._pi["max_steps"],
            "issue_token": self._kernel.mcp.issue_run_token,
            "revoke_token": self._kernel.mcp.revoke,
        }
        if context is not None and context.run_id:
            run_id = context.run_id
            cfg["event_sink"] = lambda ev: self._kernel.events.publish(context.tenant_id, run_id, ev)
        return cfg

    def _rivet_config(
        self, capability: AgentCapability, runtime_override: str | None
    ) -> dict[str, Any] | None:
        if capability.runtime not in {"rivet", "rivet_agentos", "rivet-agentos"} and (
            runtime_override != "rivet_agentos"
        ):
            return None
        return {
            "agentos_url": self._rivet["agentos_url"],
            "mcp_url": self._rivet["mcp_url"],
            "run_path": self._rivet["run_path"],
            "issue_token": self._kernel.mcp.issue_run_token,
            "revoke_token": self._kernel.mcp.revoke,
        }

    def _codex_config(
        self, capability: AgentCapability, runtime_override: str | None
    ) -> dict[str, Any] | None:
        """The injected trusted-Codex config, gated ONLY on ``capability.runtime``.

        Codex is a trusted, hard-walled lane ([2026] VJS-CC-VJS 2), NOT a
        provider-routing target: an ai_config ``runtime_override == "codex"`` must
        never select it, so (unlike the opencode/rivet lanes) this never triggers on
        the override. None when the capability is not a codex runtime, or when no
        provider was injected (off by default = no-op -> ScriptRuntime).
        """
        if capability.runtime != "codex":
            return None
        return self._codex

    def _opencode_config(
        self, capability: AgentCapability, runtime_override: str | None
    ) -> dict[str, Any] | None:
        if capability.runtime != "opencode" and runtime_override != "opencode":
            return None
        return {
            "mcp_url": os.environ.get("BOLTRIG_OPENCODE_MCP_URL")
            or os.environ.get("BOLTRIG_MCP_URL")
            or None,
            "issue_token": self._kernel.mcp.issue_run_token,
            "revoke_token": self._kernel.mcp.revoke,
        }
