"""Shared exact-counter projections for realtime call persistence."""

USAGE_COUNTERS = (
    "input_audio_bytes",
    "output_audio_bytes",
    "tool_calls",
    "provider_input_tokens",
    "provider_output_tokens",
    "estimated_cost_micros",
)


def nonnegative_int(value) -> int:
    return max(0, int(value or 0))


def usage_summary(row) -> dict[str, int | str | None]:
    if row is None:
        return {
            **{key: 0 for key in USAGE_COUNTERS},
            "pricing_revision": None,
            "cost_status": "unpriced",
        }
    return {
        **{key: nonnegative_int(row[key]) for key in USAGE_COUNTERS},
        "pricing_revision": row["pricing_revision"],
        "cost_status": row["cost_status"] or "unpriced",
    }
