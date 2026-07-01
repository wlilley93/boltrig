"""The structured result an ephemeral agent returns (US-FLT-03/04).

Every runtime (script / hermes / claude-api) returns the same shape so the
spawner, department heads and the audit writer can treat all runtimes
uniformly. It is a frozen dataclass: a result is a fact, not mutable state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentResult:
    """The outcome of one ephemeral agent run (US-FLT-04).

    Fields:
      * ``ok`` - whether the run succeeded (a degraded run still returns
        ``ok=True`` with ``output["_degraded"]`` set, mirroring the kernel's
        degrade-don't-crash doctrine, P9).
      * ``degraded`` - whether this is a degraded fallback rather than a real
        run, so orchestration can tell an echo from a reasoned success and
        never present it as ordinary success (US-FLT-07).
      * ``output`` - the structured product of the run (the verb output when
        the result flows back through an agent-bound verb).
      * ``summary`` - a short human-readable line for audit / observability.
      * ``tokens_used`` / ``cost_micros`` - accounting attributed to this run
        (US-COST-01); zero for the deterministic script runtime.
      * ``new_work_items`` - any follow-on work the run discovered (J/EXE);
        department heads cap how many of these a single step may emit
        (US-EXE-04).
    """

    ok: bool
    output: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    tokens_used: int = 0
    cost_micros: int = 0
    new_work_items: list[Any] = field(default_factory=list)
    degraded: bool = False

    @classmethod
    def succeeded(
        cls,
        output: dict[str, Any] | None = None,
        *,
        summary: str = "",
        tokens_used: int = 0,
        cost_micros: int = 0,
        new_work_items: list[Any] | None = None,
    ) -> AgentResult:
        """Convenience constructor for a successful run."""
        return cls(
            ok=True,
            output=output or {},
            summary=summary,
            tokens_used=tokens_used,
            cost_micros=cost_micros,
            new_work_items=new_work_items or [],
        )

    @classmethod
    def degrade(
        cls, *, runtime: str, reason: str, prompt: str = "", summary: str = ""
    ) -> AgentResult:
        """A clearly-marked degraded result (no SDK / no key / backend down, P9).

        Returns ``ok=True`` so a parent tree keeps running, with ``degraded=True``
        as the first-class marker (US-FLT-07) and the degrade reason carried in
        ``output["_degraded"]`` exactly like the kernel's adapter-degrade path
        (kept for back-compat consumers of the payload).
        """
        return cls(
            ok=True,
            output={
                "_degraded": {"runtime": runtime, "reason": reason},
                "prompt": prompt,
            },
            summary=summary or f"degraded ({runtime}: {reason})",
            degraded=True,
        )
