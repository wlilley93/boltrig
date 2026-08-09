"""Corpus identity: content fingerprints, exact dedup, and the digest.

The digest is built from CONTENT hashes, not record ids: two builds that
select the same messages but scrub them differently (the PII patterns evolve)
must NOT collapse to one digest - its claim is "exactly what a trained
adapter saw". Works on any record shape carrying ``kind``, ``record_id``,
``prompt``, ``signal`` and the kind's text fields (duck-typed so this module
stays import-free of the builder).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any


def _text(r: Any) -> str:
    if r.kind == "sft":
        return str(r.completion)
    return f"{r.rejected}\x00{r.chosen}"


def record_fingerprint(r: Any) -> str:
    """Canonical content hash of ONE record."""
    payload = json.dumps(
        [r.kind, r.record_id, [list(p) for p in r.prompt], _text(r), r.signal],
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


# Signal quality for duplicate resolution, best first. Mirrors the trainer's
# replay weights: when identical turns carry different signals, the surviving
# record must be the one whose signal earns the most replay - keeping a
# clean_run copy while discarding its hitl_approved twin would silently
# discard the human anchor.
_SIGNAL_RANK = {"hitl_approved": 0, "superseded": 1, "eval_pass": 2, "clean_run": 3}


def dedupe(records: list[Any]) -> tuple[list[Any], int]:
    """Collapse exact (prompt, text) duplicates, keeping the BEST-signal copy
    (first occurrence position, so order stays stable).

    Templated flows repeat near-identical turns by the hundred; training on
    the flood over-weights the template and squeezes output entropy - the
    silent-collapse failure mode. Exact dedup is the cheap first defence;
    signal-weighted replay at the trainer is the second."""
    best: dict[str, tuple[int, Any]] = {}  # content key -> (position, record)
    order: list[str] = []
    for position, r in enumerate(records):
        key = json.dumps([[list(p) for p in r.prompt], _text(r)], sort_keys=True)
        if key not in best:
            best[key] = (position, r)
            order.append(key)
        elif _SIGNAL_RANK.get(r.signal, 9) < _SIGNAL_RANK.get(best[key][1].signal, 9):
            best[key] = (best[key][0], r)  # better signal, original position
    kept = [best[key][1] for key in order]
    return kept, len(records) - len(kept)


def corpus_digest(
    records: list[Any], base_pin: str, watermark: datetime | None
) -> str:
    h = hashlib.sha256()
    for fp in sorted(record_fingerprint(r) for r in records):
        h.update(fp.encode())
        h.update(b"\x00")
    h.update(base_pin.encode())
    h.update((watermark.isoformat() if watermark else "none").encode())
    return h.hexdigest()
