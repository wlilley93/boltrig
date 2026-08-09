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


def dedupe(records: list[Any]) -> tuple[list[Any], int]:
    """Collapse exact (prompt, text) duplicates, keeping the first.

    Templated flows repeat near-identical turns by the hundred; training on
    the flood over-weights the template and squeezes output entropy - the
    silent-collapse failure mode. Exact dedup is the cheap first defence;
    signal-weighted replay at the trainer is the second."""
    seen: set[str] = set()
    kept: list[Any] = []
    for r in records:
        key = json.dumps([[list(p) for p in r.prompt], _text(r)], sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        kept.append(r)
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
