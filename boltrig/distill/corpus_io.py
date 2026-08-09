"""JSONL serialisation for a derived distillation corpus (decision 0023).

The wire shape the trainer sidecar receives and the inspection CLI prints:
one header line (keys-only metadata, the digest, the held-out split), then one
line per record of already-scrubbed text. Never re-reads the store.
"""

from __future__ import annotations

import json
from typing import Any, Iterator

from boltrig.distill.corpus import Corpus, SftRecord


def corpus_jsonl_lines(corpus: Corpus) -> Iterator[str]:
    header = {
        "kind": "corpus",
        "tenant_id": corpus.tenant_id,
        "base_pin": corpus.base_pin,
        "digest": corpus.digest,
        "erasure_watermark": (
            corpus.erasure_watermark.isoformat() if corpus.erasure_watermark else None
        ),
        "records": len(corpus.records),
        "held_out": list(corpus.held_out),
    }
    yield json.dumps(header, sort_keys=True)
    for r in corpus.records:
        row: dict[str, Any] = {
            "kind": r.kind,
            "record_id": r.record_id,
            "tenant_id": r.tenant_id,
            "conversation_id": r.conversation_id,
            "run_id": r.run_id,
            "prompt": [list(pair) for pair in r.prompt],
            "signal": r.signal,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        if isinstance(r, SftRecord):
            row["completion"] = r.completion
            row["eval_score"] = r.eval_score
        else:
            row["rejected"] = r.rejected
            row["chosen"] = r.chosen
        yield json.dumps(row, sort_keys=True)
