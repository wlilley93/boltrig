"""Mean token log-likelihood of held-out completions (the register gate's ruler).

Runs inside the mlx venv (``BOLTRIG_DISTILL_MLX_PYTHON``), invoked by app.py as
a subprocess. Prints ONE number on the last stdout line: the mean per-token
log-likelihood of each record's assistant completion given its prompt, averaged
over all records. Higher (less negative) = the model finds the tenant's
accepted replies more probable.

No sampling, no judge - teacher-forced scoring only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--adapter", default=None)
    parser.add_argument("--data", required=True)
    args = parser.parse_args()

    try:
        import mlx.core as mx
        from mlx_lm import load
    except ImportError as exc:
        print(f"mlx_lm unavailable: {exc}", file=sys.stderr)
        return 3

    model, tokenizer = load(args.model, adapter_path=args.adapter)

    total_logprob = 0.0
    total_tokens = 0
    for line in Path(args.data).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        prompt = [
            {"role": role, "content": content} for role, content in record["prompt"]
        ]
        completion = record["completion"]
        prompt_ids = tokenizer.apply_chat_template(
            prompt, add_generation_prompt=True
        )
        full_ids = tokenizer.apply_chat_template(
            prompt + [{"role": "assistant", "content": completion}],
            add_generation_prompt=False,
        )
        if len(full_ids) <= len(prompt_ids):
            continue
        tokens = mx.array([full_ids])
        logits = model(tokens[:, :-1])
        logprobs = logits - mx.logsumexp(logits, axis=-1, keepdims=True)
        # score only the completion span, teacher-forced
        span = range(max(len(prompt_ids) - 1, 0), len(full_ids) - 1)
        for pos in span:
            target = full_ids[pos + 1]
            total_logprob += float(logprobs[0, pos, target])
            total_tokens += 1

    if total_tokens == 0:
        print("no scoreable tokens", file=sys.stderr)
        return 2
    print(total_logprob / total_tokens)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
