"""The single adapter interface (S7.3).

Every adapter, regardless of source (generated / builtin / manual) or runtime
(http / sql / mq / file / script), implements this one Protocol. The kernel
loads adapters dynamically (P1) and is the only caller of ``execute`` - it
passes a resolved ``Credential`` that never leaves the kernel boundary (K-20).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from boltrig.models import InvocationContext


@dataclass(frozen=True)
class Credential:
    """Resolved secret material. Constructed inside the kernel at call time and
    handed to an adapter for the duration of one call. It is never serialised
    into a result, returned to an agent, or written to audit (SEC-05, K-20)."""

    id: str
    kind: str  # 'oauth' | 'api_key' | 'basic' | 'mtls' | ...
    material: dict[str, Any] = field(default_factory=dict, repr=False)  # repr-suppressed

    def __str__(self) -> str:  # defensive: never leak material via str()
        return f"<Credential {self.id} ({self.kind})>"


class ErrorClass(str, Enum):
    """Common error taxonomy adapters map their native errors onto (S7.3)."""

    NOT_FOUND = "not_found"
    UNAUTHORISED = "unauthorised"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"  # backend down -> may trigger degraded mode
    INVALID = "invalid"
    CONFLICT = "conflict"
    INTERNAL = "internal"


@dataclass(frozen=True)
class AdapterError:
    error_class: ErrorClass
    message: str
    retryable: bool = False
    retry_after_seconds: float | None = None


@dataclass(frozen=True)
class Result:
    """The outcome of an adapter call. ``output`` must match the verb's output
    schema when ``ok`` is true."""

    ok: bool
    output: dict[str, Any] = field(default_factory=dict)
    error: AdapterError | None = None

    @classmethod
    def success(cls, output: dict[str, Any]) -> Result:
        return cls(ok=True, output=output)

    @classmethod
    def failure(cls, error: AdapterError) -> Result:
        return cls(ok=False, error=error)


@dataclass(frozen=True)
class VerbSpec:
    """A verb an adapter provides, returned by ``describe()`` so the kernel can
    register verbs + bindings and recommended rate limits without code (P1)."""

    verb_id: str
    noun_id: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    consequence: str = "low"
    description: str = ""
    rate_limit: dict[str, Any] | None = None
    degraded_mode: dict[str, Any] | None = None
    # ``disabled`` is for one-time/bearer-secret results that must never be
    # persisted for replay (for example an invitation token).  It is declarative
    # adapter data, not a kernel hard-coded verb list.
    idempotency_mode: str = "cacheable"


@runtime_checkable
class Adapter(Protocol):
    id: str
    version: str
    runtime: str  # 'http' | 'sql' | 'mq' | 'file' | 'script'

    def describe(self) -> list[VerbSpec]:
        """The verbs this adapter provides, with schemas + recommended limits."""
        ...

    async def execute(
        self,
        verb: str,
        params: dict[str, Any],
        credential: Credential | None,
        context: InvocationContext,
    ) -> Result:
        """Perform the action. Implements retry/backoff, pagination, rate-limit
        cooperation, and error mapping to ``ErrorClass`` internally."""
        ...

    async def health(self) -> str:  # 'ok' | 'degraded' | 'down'
        ...
