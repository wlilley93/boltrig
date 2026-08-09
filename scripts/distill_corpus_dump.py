#!/usr/bin/env python3
"""Dump a tenant's sleep-distillation corpus as JSONL for inspection.

Read-only: derives the corpus (decision 0023) from the governed record and
prints it - the same derivation the `distill.corpus.build` verb runs, so what
you inspect here is what a trainer would see. Never writes to the store.

Usage:
    .venv/bin/python scripts/distill_corpus_dump.py \
        --tenant acme \
        --base-pin mlx-community/Qwen2.5-7B-Instruct-4bit@main \
        --database-url postgresql://... \
        [--out corpus.jsonl]

With no --database-url it falls back to $BOLTRIG_TEST_DATABASE_URL, and
refuses to run without either (an empty in-memory corpus proves nothing).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from boltrig.distill import build_corpus, corpus_jsonl_lines  # noqa: E402


async def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--base-pin", required=True,
                        help="exact base model repo+revision the adapter trains from")
    parser.add_argument("--database-url", default=os.environ.get("BOLTRIG_TEST_DATABASE_URL"))
    parser.add_argument("--out", default=None, help="write JSONL here (default: stdout)")
    args = parser.parse_args()

    if not args.database_url:
        print("error: --database-url (or BOLTRIG_TEST_DATABASE_URL) is required",
              file=sys.stderr)
        return 2

    from boltrig.store.postgres import PostgresStore

    store = await PostgresStore.connect(args.database_url, apply_schema=False)
    corpus = await build_corpus(
        store,
        args.tenant,
        base_pin=args.base_pin,
        target_tenant_id=args.tenant,
        target_data_class="sensitive",
    )
    lines = list(corpus_jsonl_lines(corpus))
    if args.out:
        Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        for line in lines:
            print(line)
    print(
        f"records={len(corpus.records)} held_out={len(corpus.held_out)} "
        f"digest={corpus.digest[:16]}... watermark={corpus.erasure_watermark}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
