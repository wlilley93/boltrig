"""Distinct-2 diversity of sampled generations (the entropy guard's ruler).

Runs inside the mlx venv, invoked by app.py as a subprocess. Generates one
sampled completion per held-out prompt at a fixed temperature, then prints ONE
number on the last stdout line: distinct bigrams / total bigrams across all
generations pooled. A model collapsing onto a template repeats the same
n-grams everywhere and this ratio falls; likelihood alone never notices.

Seeded from the corpus digest by the caller, so a gate re-run over the same
corpus samples the same generations (replayable, like everything else in the
gate).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _distinct_2(texts: list[str]) -> float:
    bigrams: list[tuple[str, str]] = []
    for text in texts:
        tokens = text.split()
        bigrams.extend(zip(tokens, tokens[1:]))
    if not bigrams:
        return 0.0
    return len(set(bigrams)) / len(bigrams)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--adapter", default=None)
    parser.add_argument("--data", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--temp", type=float, default=0.8)
    parser.add_argument("--max-tokens", type=int, default=128)
    args = parser.parse_args()

    try:
        import mlx.core as mx
        from mlx_lm import generate, load
        from mlx_lm.sample_utils import make_sampler
    except ImportError as exc:
        print(f"mlx_lm unavailable: {exc}", file=sys.stderr)
        return 3

    mx.random.seed(args.seed)
    model, tokenizer = load(args.model, adapter_path=args.adapter)
    sampler = make_sampler(temp=args.temp)

    texts: list[str] = []
    for line in Path(args.data).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        prompt = [
            {"role": role, "content": content} for role, content in record["prompt"]
        ]
        prompt_text = tokenizer.apply_chat_template(
            prompt, add_generation_prompt=True, tokenize=False
        )
        texts.append(
            generate(
                model, tokenizer, prompt=prompt_text,
                max_tokens=args.max_tokens, sampler=sampler,
            )
        )

    if not texts:
        print("no prompts to sample", file=sys.stderr)
        return 2
    print(_distinct_2(texts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
