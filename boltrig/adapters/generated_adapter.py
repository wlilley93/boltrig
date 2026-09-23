"""The generated-adapter runtime classes (arc-1 structural move from
``boltrig/adapters/generator.py``): ``_Operation``, the SEC-22 ``ReviewGate``
and ``GeneratedAdapter``. The derivation half stays in ``generator.py``.
Behaviour- and import-surface-preserving (generator.py re-exports).
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import quote

from boltrig.adapters.base import AdapterError, Credential, ErrorClass, Result, VerbSpec
from boltrig.adapters.http_base import Handler, HttpAdapter, RateLimitConfig, RetryPolicy
from boltrig.models import InvocationContext, utcnow


@dataclass(frozen=True)
class _Operation:
    """The derived, deterministic description of one OpenAPI operation."""

    verb_id: str
    noun_id: str
    method: str
    path: str  # template with {param} placeholders
    path_params: tuple[str, ...]
    query_params: tuple[str, ...]
    header_params: tuple[str, ...]
    has_body: bool
    consequence: str
    pagination: str | None  # 'link' | 'offset' | None
    items_key: str
    next_key: str


@dataclass
class ReviewGate:
    """Human-in-the-loop activation gate for a generated adapter (SEC-22).

    A generated adapter stays inert until a NAMED reviewer activates it. The
    registry consults ``activated`` before creating any binding.
    """

    activated: bool = False
    reviewer: str | None = None
    reviewed_at: datetime | None = None

    def activate(self, reviewer: str) -> None:
        if not reviewer:
            raise ValueError("a reviewer id is required to activate a generated adapter")
        self.activated = True
        self.reviewer = reviewer
        self.reviewed_at = utcnow()


class GeneratedAdapter(HttpAdapter):
    """An :class:`HttpAdapter` whose verbs were derived from an OpenAPI document.

    Inert until :meth:`review_and_activate` is called (SEC-22).
    """

    version = "1.0.0-generated"

    def __init__(
        self,
        *,
        adapter_id: str,
        base_url: str,
        operations: dict[str, _Operation],
        verbspecs: list[VerbSpec],
        rate_limit: RateLimitConfig,
        spec_title: str = "",
        network_config: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            base_url=base_url,
            rate_limit=rate_limit,
            retry=RetryPolicy(),
            network_config=network_config,
        )
        self.id = adapter_id
        self._operations = operations
        self._verbspecs = verbspecs
        self._gate = ReviewGate()
        self._spec_title = spec_title

    # --- review gate ---------------------------------------------------------
    @property
    def activated(self) -> bool:
        return self._gate.activated

    @property
    def review_gate(self) -> ReviewGate:
        return self._gate

    def review_and_activate(self, reviewer: str) -> ReviewGate:
        """Record human review and activate the adapter (SEC-22). Only after this
        may the registry create bindings for the adapter's verbs."""
        self._gate.activate(reviewer)
        return self._gate

    # --- contract surface ----------------------------------------------------
    def describe(self) -> list[VerbSpec]:
        return list(self._verbspecs)

    def _handlers(self) -> dict[str, Handler]:
        # One typed handler closure per derived operation.
        return {verb: functools.partial(self._invoke, verb) for verb in self._operations}

    async def execute(
        self,
        verb: str,
        params: dict[str, Any],
        credential: Credential | None,
        context: InvocationContext,
    ) -> Result:
        if not self._gate.activated:
            return Result.failure(
                AdapterError(
                    ErrorClass.UNAVAILABLE,
                    "generated adapter is inert pending human review (SEC-22)",
                )
            )
        return await super().execute(verb, params, credential, context)

    async def _invoke(
        self, verb: str, params: dict[str, Any], client: Any, context: InvocationContext
    ) -> Result:
        op = self._operations[verb]
        path = op.path
        for name in op.path_params:
            if name not in params:
                return Result.failure(
                    AdapterError(ErrorClass.INVALID, f"missing path parameter {name}")
                )
            path = path.replace("{%s}" % name, quote(str(params[name]), safe=""))
        query = {name: params[name] for name in op.query_params if name in params}
        headers = {name: str(params[name]) for name in op.header_params if name in params}
        json_body = params.get("body") if op.has_body else None

        if op.method == "get" and op.pagination == "link":
            items = [
                item
                async for item in self.paginate(
                    client,
                    path,
                    params=query or None,
                    items_key=op.items_key,
                    next_key=op.next_key,
                )
            ]
            return Result.success({"items": items, "count": len(items)})
        if op.method == "get" and op.pagination == "offset":
            items = [
                item
                async for item in self.paginate_offset(
                    client, path, params=query or None, items_key=op.items_key
                )
            ]
            return Result.success({"items": items, "count": len(items)})

        body = await self.request(
            client,
            op.method.upper(),
            path,
            params=query or None,
            json=json_body,
            headers=headers or None,
        )
        return Result.success(body)

    # --- reviewable artefact (SEC-22) ---------------------------------------
    def render_source(self) -> str:
        """Emit a human-reviewable Python module for this generated adapter.

        The runtime instance already carries every behaviour; this string is the
        artefact a reviewer reads before calling :meth:`review_and_activate`.
        """
        lines: list[str] = [
            '"""Generated adapter (US-ADP-01). Source spec: '
            f'{self._spec_title or "unknown"}.',
            "",
            "Derived deterministically from an OpenAPI document. Inherits retry/",
            "backoff, error mapping, rate-limit cooperation and pagination from",
            "HttpAdapter. INERT until a human reviewer activates it (SEC-22).",
            '"""',
            "from __future__ import annotations",
            "",
            "from boltrig.adapters.http_base import HttpAdapter, RateLimitConfig",
            "",
            "",
            f"class {self._class_name()}(HttpAdapter):",
            f"    id = {self.id!r}",
            f"    version = {self.version!r}",
            f"    base_url = {self.base_url!r}",
            "    rate_limit_config = RateLimitConfig("
            f"max={self.rate_limit.max}, per={self.rate_limit.per!r})",
            "",
            "    # verb -> (method, path, consequence, pagination)",
            "    OPERATIONS = {",
        ]
        for verb, op in self._operations.items():
            lines.append(
                f"        {verb!r}: ({op.method.upper()!r}, {op.path!r}, "
                f"{op.consequence!r}, {op.pagination!r}),"
            )
        lines.append("    }")
        lines.append("")
        lines.append("    # Typed handlers are built from OPERATIONS at load time")
        lines.append("    # (see boltrig.adapters.generator.GeneratedAdapter).")
        lines.append("")
        return "\n".join(lines)

    def _class_name(self) -> str:
        parts = [p for p in self.id.replace("-", "_").split("_") if p]
        return "".join(p.capitalize() for p in parts) + "Adapter" or "GeneratedAdapter"
