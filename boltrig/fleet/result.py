"""The structured result an ephemeral agent returns (US-FLT-03/04).

Every runtime (script / codex / typed-unavailable) returns the same shape so the
spawner, department heads and the audit writer can treat all runtimes
uniformly. It is a frozen dataclass: a result is a fact, not mutable state.
"""

from __future__ import annotations

import hashlib
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
      * ``input_tokens`` / ``output_tokens`` - the runtime's split of
        ``tokens_used`` when it reports one, so the accountant can price each
        leg at its own rate. Optional and additive: 0/0 means "this runtime
        cannot split its usage" and prices exactly as it did before.
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
    # The input/output split of ``tokens_used`` when the runtime reports one
    # (Codex does, on `thread/tokenUsage/updated`). APPENDED and defaulting to 0
    # so every existing runtime, caller and positional construction is untouched;
    # a 0/0 result is priced at a single rate on the total exactly as before,
    # never at zero.
    #
    # It exists because input and output are NOT the same price: on the rate cards
    # the fleet bills from they differ by more than 2x (the tenant chat model is
    # $0.35 in / $0.75 out per 1M tokens), and an agent turn is heavily
    # input-weighted, so pricing a whole turn at the output rate over-bills it
    # substantially and trips a hard-stop budget early.
    input_tokens: int = 0
    output_tokens: int = 0

    @classmethod
    def succeeded(
        cls,
        output: dict[str, Any] | None = None,
        *,
        summary: str = "",
        tokens_used: int = 0,
        cost_micros: int = 0,
        new_work_items: list[Any] | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> AgentResult:
        """Convenience constructor for a successful run."""
        return cls(
            ok=True,
            output=output or {},
            summary=summary,
            tokens_used=tokens_used,
            cost_micros=cost_micros,
            new_work_items=new_work_items or [],
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    @property
    def degrade_reason(self) -> str | None:
        """The bounded degrade tag this result carries, or None.

        Read here because ``degrade`` writes it here. It is a runtime tag plus an
        exception CLASS name ("codex_turn_failed:CodexRuntimeOperationError") - never
        the prompt, the output, or the exception's args - so it is safe on the audit
        row, where its absence meant a degraded turn recorded WHAT failed but not why.
        """
        marker = self.output.get("_degraded") if isinstance(self.output, dict) else None
        reason = marker.get("reason") if isinstance(marker, dict) else None
        return str(reason)[:200] if reason else None

    @classmethod
    def degrade(
        cls,
        *,
        runtime: str,
        reason: str,
        prompt: str = "",
        summary: str = "",
        tokens_used: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> AgentResult:
        """A clearly-marked degraded result (no SDK / no key / backend down, P9).

        Returns ``ok=True`` so a parent tree keeps running, with ``degraded=True``
        as the first-class marker (US-FLT-07) and the degrade reason carried in
        ``output["_degraded"]`` exactly like the kernel's adapter-degrade path
        (kept for back-compat consumers of the payload). The prompt is NEVER
        embedded verbatim - it is the full composed prompt (skill fragments +
        task), returned to callers and persisted on work-item results - so the
        output carries only its sha256 digest and byte length for correlation.

        ``tokens_used`` exists because a degrade is not the same as a free run. A
        model can be called, consume its tokens and THEN produce an unusable answer
        (the empty-output case) - the provider has already been paid. Defaulting it
        to 0 and having no way to say otherwise meant every degraded run recorded as
        costing nothing, and the budget was refunded in full, so a tenant could burn
        real money on failing turns and never see it. Callers pass what the runtime
        actually reported; a degrade that genuinely knows nothing still passes 0.
        The input/output split rides along for the same reason: a paid-for turn is
        priced leg by leg whether or not it produced a usable answer.
        """
        prompt_bytes = prompt.encode("utf-8")
        return cls(
            ok=True,
            output={
                "_degraded": {"runtime": runtime, "reason": reason},
                "prompt_sha256": hashlib.sha256(prompt_bytes).hexdigest(),
                "prompt_bytes": len(prompt_bytes),
            },
            summary=summary or f"degraded ({runtime}: {reason})",
            degraded=True,
            tokens_used=max(0, int(tokens_used or 0)),
            input_tokens=max(0, int(input_tokens or 0)),
            output_tokens=max(0, int(output_tokens or 0)),
        )


def reply_text(result: dict[str, Any]) -> str:
    """The USER-FACING reply from a spawn result: the runtime's output text.

    ``summary`` is only the fallback, and the distinction above is load-bearing.
    It is documented there as "a short human-readable line for audit /
    observability", and the codex lane builds it as ``text[:256]``
    (codex_runtime.py:304). Using it as the reply capped EVERY chat answer at 256
    characters, mid-word, with status=ok and no error anywhere - so short answers
    looked perfect while substantive ones were decapitated.

    Lives here, beside the field contract it turns on, rather than at the chat
    seam: a caller that wants a reply should not need runtime-specific result
    knowledge. Degraded results carry no ``output["text"]`` (only
    ``output["_degraded"]``), so they fall through to ``summary`` unchanged.
    """
    output = result.get("output")
    text = output.get("text") if isinstance(output, dict) else None
    return text or result.get("summary") or "Done."
