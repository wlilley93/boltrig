"""Resolve model endpoints and build runtimes for ephemeral spawns."""

from __future__ import annotations

import os
from typing import Any, cast

from boltrig.config.environment import production_signal
from boltrig.models import (
    AgentCapability,
    CredentialResolution,
    InvocationContext,
    ModelEndpoint,
    ModelEndpointUnavailable,
)

from .codex_model_selection import (
    codex_model_route,
    resolve_base_model,
    resolve_codex_model,
)
from .model_gateway import ModelGateway, gateway_config
from .runtime import Runtime, build_runtime
from .runtime_endpoint_policy import (
    apply_conversation_gateway,
    served_model_route,
)


class PinnedRuntimePolicyUnavailable(RuntimeError):
    """A composed runtime cannot honestly satisfy an authored pinned profile."""


class RuntimeResolver:
    """Owns runtime routing while leaving spawn orchestration thin."""

    def __init__(
        self,
        kernel: Any,
        *,
        sensitive_endpoint_id: str | None = None,
        codex_config: dict[str, Any] | None = None,
        model_catalogue: Any = None,
    ) -> None:
        self._kernel = kernel
        self._sensitive_endpoint_id = sensitive_endpoint_id
        # Trusted read-only Codex provider config, injected from the api composition
        # root ([2026] VJS-CC-VJS 2). None (the default) => the codex runtime is a
        # degrade-marked unavailable lane (off by default = total no-op).
        self._codex = codex_config
        self._model_catalogue = model_catalogue
        self._gateway = gateway_config()
        self._bindings = ModelGateway(ttl_seconds=int(cast(int, self._gateway["ttl_seconds"])))

    async def runtime_for(
        self,
        tenant_id: str,
        capability: AgentCapability,
        context: InvocationContext | None = None,
        *,
        pinned_policy: bool = False,
        allow_kernel_tools: bool = True,
    ) -> Runtime:
        """Resolve one runtime under either caller-routing or pinned profile policy.

        ``pinned_policy`` is reserved for process-composed permanent profiles.  It
        keeps the authored runtime/model endpoint authoritative while retaining
        every shared safety boundary in this resolver: sensitive-data routing,
        scoped credential resolution, the model gateway, the trusted Codex wall,
        and typed unavailable runtimes.  In particular, a user's AI-key provider
        choice or model-profile hint cannot silently turn an authored permanent
        Codex head into a different runtime. ``allow_kernel_tools`` lets a caller
        retain the same resolver/admission path while explicitly selecting the
        read-only Codex phase; permanent routing/decomposition uses that posture
        because its authored skills govern child selection, not side effects in
        the routing call itself.
        """
        endpoint, model_route, gateway_virtual_key = (
            await self._resolve_runtime_policy_with_binding(
                tenant_id,
                capability,
                context,
                pinned_policy=pinned_policy,
            )
        )
        self._require_pinned_codex_model(
            capability,
            endpoint,
            pinned_policy=pinned_policy,
        )
        runtime = self._build_resolved_runtime(
            capability,
            endpoint,
            model_route,
            gateway_virtual_key=gateway_virtual_key,
            allow_kernel_tools=allow_kernel_tools,
        )
        self._attach_model_route(runtime, endpoint, model_route)
        return runtime

    async def _resolve_runtime_policy_with_binding(
        self,
        tenant_id: str,
        capability: AgentCapability,
        context: InvocationContext | None,
        *,
        pinned_policy: bool,
    ) -> tuple[ModelEndpoint | None, dict[str, str] | None, str | None]:
        (
            sensitive,
            modality,
            selected_endpoint_id,
            _capability_endpoint_id,
            endpoint,
        ) = await resolve_base_model(
            kernel=self._kernel,
            tenant_id=tenant_id,
            capability=capability,
            context=context,
            pinned_policy=pinned_policy,
            sensitive_endpoint_id=self._sensitive_endpoint_id,
        )
        model_route: dict[str, str] | None = None
        gateway_virtual_key: str | None = None

        if capability.runtime == "codex" and not sensitive:
            endpoint, gateway_virtual_key = await self._resolve_codex_endpoint(
                tenant_id,
                capability,
                context,
                endpoint,
                selected_endpoint_id=selected_endpoint_id,
                modality=modality,
                pinned_policy=pinned_policy,
            )

        conversation_id = context.extra.get("conversation_id") if context is not None else None
        endpoint = apply_conversation_gateway(
            endpoint,
            gateway_url=cast(str | None, self._gateway["base_url"]),
            bindings=self._bindings,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            sensitive=sensitive,
            capability=capability,
            choice_id=selected_endpoint_id,
            pinned_policy=pinned_policy,
        )
        if capability.runtime == "codex" and endpoint is not None and not sensitive:
            model_route = codex_model_route(endpoint, selected_endpoint_id)
        return endpoint, model_route, gateway_virtual_key

    async def _resolve_codex_endpoint(
        self,
        tenant_id: str,
        capability: AgentCapability,
        context: InvocationContext | None,
        endpoint: ModelEndpoint | None,
        *,
        selected_endpoint_id: str | None,
        modality: str,
        pinned_policy: bool,
    ) -> tuple[ModelEndpoint | None, str | None]:
        material, resolution = await self._resolve_ai_key(tenant_id, context, modality)
        gateway_url = cast(str | None, self._gateway["base_url"])
        if (
            not pinned_policy
            and selected_endpoint_id is None
            and resolution is not None
            and not resolution.is_default
        ):
            return await self._scoped_default_endpoint(
                tenant_id, modality, gateway_url, resolution, material
            )
        resolved = await resolve_codex_model(
            kernel=self._kernel,
            tenant_id=tenant_id,
            capability=capability,
            endpoint=endpoint,
            choice_id=selected_endpoint_id,
            modality=modality,
            pinned_policy=pinned_policy,
            codex_config=self._codex,
            gateway_url=gateway_url,
            model_catalogue=self._model_catalogue,
        )
        return resolved, None

    async def _scoped_default_endpoint(
        self,
        tenant_id: str,
        modality: str,
        gateway_url: str | None,
        resolution: Any,
        material: str | None,
    ) -> tuple[ModelEndpoint, str]:
        if material is None:
            raise CredentialResolution("configured AI credential material is unavailable")
        from boltrig.identity.bifrost_user_binding import (
            BifrostUserBindingUnavailable,
            BifrostUserGateway,
        )

        try:
            binding = await BifrostUserGateway().ensure(
                self._kernel.store, tenant_id, resolution, material
            )
        except BifrostUserBindingUnavailable as error:
            raise ModelEndpointUnavailable(
                "the configured AI provider is not ready"
            ) from error
        endpoint = ModelEndpoint(
            id="scoped-ai-default",
            tenant_id=tenant_id,
            kind="bifrost",
            model=binding.model_id,
            base_url=gateway_url,
            data_class="standard",
            modalities=(modality,),
        )
        return endpoint, binding.virtual_key

    def _require_pinned_codex_model(
        self,
        capability: AgentCapability,
        endpoint: ModelEndpoint | None,
        *,
        pinned_policy: bool,
    ) -> None:
        if (
            pinned_policy
            and capability.runtime == "codex"
            and self._codex is not None
            and endpoint is not None
        ):
            composed_model = str(self._codex.get("model_id") or "").strip()
            if not composed_model or endpoint.model != composed_model:
                raise PinnedRuntimePolicyUnavailable(
                    "the composed Codex model does not satisfy the pinned profile"
                )

    def _build_resolved_runtime(
        self,
        capability: AgentCapability,
        endpoint: ModelEndpoint | None,
        model_route: dict[str, str] | None,
        *,
        gateway_virtual_key: str | None,
        allow_kernel_tools: bool,
    ) -> Runtime:
        def lookup(endpoint_id: str) -> ModelEndpoint | None:
            if endpoint is not None and endpoint.id == endpoint_id:
                return endpoint
            return None

        return build_runtime(
            capability,
            lookup,
            codex_config=self._codex_config(
                capability,
                model_id=(endpoint.model if endpoint is not None else None),
                model_endpoint_id=(
                    model_route.get("choice_id") if model_route is not None else None
                ),
                gateway_virtual_key=gateway_virtual_key,
                allow_kernel_tools=allow_kernel_tools,
            ),
        )

    def _attach_model_route(
        self,
        runtime: Runtime,
        endpoint: ModelEndpoint | None,
        model_route: dict[str, str] | None,
    ) -> None:
        """Record the model that actually served the call.

        A profile route wins because it carries richer attribution. Otherwise the
        resolved endpoint makes cost and decision provenance independently
        checkable. An unavailable runtime gets no speculative model label.
        """
        if model_route is None:
            model_route = served_model_route(endpoint)
        if model_route:
            setattr(runtime, "model_route", model_route)

    async def _resolve_ai_key(
        self, tenant_id: str, context: InvocationContext | None, modality: str = "text"
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
                modality=modality,
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

    def _codex_config(
        self,
        capability: AgentCapability,
        *,
        model_id: str | None = None,
        model_endpoint_id: str | None = None,
        gateway_virtual_key: str | None = None,
        allow_kernel_tools: bool = True,
    ) -> dict[str, Any] | None:
        """The injected trusted-Codex config, gated ONLY on ``capability.runtime``.

        Codex is a trusted, hard-walled lane ([2026] VJS-CC-VJS 2), not a
        provider-routing target. None when the capability is not Codex, or when no
        provider was injected (off by default = no-op -> unavailable lane).

        A capability with ``supported_skills: ['*']`` selects the kernel-tools
        lane (real tool use through the kernel's MCP face); anything narrower
        keeps the read-only analysis lane. The marker carries the SAME
        run-scoped-token + revocation idiom (``kernel.mcp.issue_run_token``),
        the kernel MCP endpoint, and the
        tool-ceiling compiler (the kernel MCP tools/list derivation), so the
        adapter needs no store or kernel handle of its own.
        """
        if capability.runtime != "codex":
            return None
        if self._codex is None:
            return None
        cfg = dict(self._codex)
        if model_id:
            cfg["model_id"] = model_id
        cfg["model_endpoint_id"] = model_endpoint_id
        cfg["gateway_virtual_key"] = gateway_virtual_key
        cfg["kernel_tools"] = allow_kernel_tools and "*" in (capability.supported_skills or [])
        cfg["issue_token"] = self._kernel.mcp.issue_run_token
        cfg["revoke_token"] = self._kernel.mcp.revoke
        cfg["mcp_url"] = (
            os.environ.get("BOLTRIG_CODEX_MCP_URL")
            or os.environ.get("BOLTRIG_MCP_URL")
            or "http://kernel:8000/v1/mcp"
        )
        cfg["compile_tool_ceiling"] = self._compile_codex_tool_ceiling
        return cfg

    async def _compile_codex_tool_ceiling(self, tenant_id: str, grants: Any) -> tuple[str, ...]:
        """The run's effective kernel tool set: tenant ceiling ∩ run grants.

        Byte-for-byte the kernel MCP face's ``tools/list`` derivation
        (FR-MCP-02), so the admission-compiled proxy ceiling and the tools the
        kernel will actually advertise to the cell are the same set.
        """
        permissions = await self._kernel.store.get_tenant_permissions(tenant_id)
        verbs = await self._kernel.store.list_verbs(tenant_id)
        return tuple(
            verb.id
            for verb in verbs
            if permissions.grants.permits(verb.id) and grants.permits(verb.id)
        )
