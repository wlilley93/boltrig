"""The distill trainer/scorer sidecar (decision 0023).

Runs NATIVE on the Mac host - mlx needs Metal, and Metal does not exist inside
the OrbStack Linux VM (the whisper precedent). The kernel's distill adapter
reaches it at a fixed operator-configured URL through the egress guard's
``allow_internal`` opt-in.

Stdlib-only HTTP surface; mlx-lm is invoked as a SUBPROCESS in its own venv
(``BOLTRIG_DISTILL_MLX_PYTHON``), so this file has no ML dependency and the
service degrades typed - a missing mlx install answers 503, never a crash.

Routes:
    GET  /health              {"status": "ok", "mlx": bool}
    PUT  /corpus/{digest}     store a shipped corpus (header digest must match)
    POST /train               {corpus_digest, adapter_kind, base_pin}
    POST /loglik              {corpus_digest, model}
    POST /diversity           {corpus_digest, model}  (entropy guard, DIS-9)

Two contract clauses are load-bearing (DIS-4):
  * /train refuses a corpus whose header ``base_pin`` differs from the
    request's - the kernel side sends its composed pin, so a drifted corpus
    cannot silently train from another base;
  * training always starts from the bare base model. There is no field, path
    or flag through which a prior adapter can seed a run.

Held-out records (the corpus header's ``held_out`` list) are EXCLUDED from
training for both adapter kinds: for register they are the gate's scoring set
(training on them would let a candidate pass by memorising its own exam), and
for craft the same exclusion keeps the two corpora identical.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_BODY = 256 * 1024 * 1024  # a corpus of chat text; bounded, not unlimited

STATE_DIR = Path(
    os.environ.get("BOLTRIG_DISTILL_STATE")
    or Path.home() / ".local" / "state" / "boltrig-distill"
)
MLX_PYTHON = os.environ.get("BOLTRIG_DISTILL_MLX_PYTHON") or sys.executable
PORT = int(os.environ.get("BOLTRIG_DISTILL_PORT") or "8930")
# Loopback by default: an unauthenticated trainer must not face the LAN.
# OrbStack machines reach host-loopback services via host.orb.internal;
# set BOLTRIG_DISTILL_BIND if a deployment genuinely needs otherwise.
BIND = os.environ.get("BOLTRIG_DISTILL_BIND") or "127.0.0.1"

# Per-kind training knobs: register is a lower-touch weekly pass over tone;
# craft is the nightly behaviour pass. Deliberately conservative defaults.
# Batch size is pinned because train/valid splits must each hold at least one
# full batch (mlx_lm refuses otherwise) - _BATCH also drives the split floor.
_BATCH = 2
_TRAIN_ARGS = {
    "craft": ["--iters", "600", "--learning-rate", "1e-5"],
    "register": ["--iters", "200", "--learning-rate", "2e-6"],
}
_MIN_TRAINABLE = _BATCH * 3  # one valid batch + at least two train batches


def corpora_dir() -> Path:
    return STATE_DIR / "corpora"


def adapters_dir() -> Path:
    return STATE_DIR / "adapters"


def mlx_available() -> bool:
    probe = subprocess.run(
        [MLX_PYTHON, "-c", "import mlx_lm"], capture_output=True, timeout=30
    )
    return probe.returncode == 0


def parse_corpus(jsonl: str) -> tuple[dict, list[dict]]:
    lines = [line for line in jsonl.splitlines() if line.strip()]
    if not lines:
        raise ValueError("empty corpus")
    header = json.loads(lines[0])
    if header.get("kind") != "corpus":
        raise ValueError("first line is not a corpus header")
    return header, [json.loads(line) for line in lines[1:]]


def store_corpus(digest: str, jsonl: str) -> dict:
    if not _DIGEST_RE.match(digest):
        raise ValueError("bad digest")
    header, records = parse_corpus(jsonl)
    if header.get("digest") != digest:
        raise ValueError("corpus header digest does not match the path digest")
    corpora_dir().mkdir(parents=True, exist_ok=True)
    (corpora_dir() / f"{digest}.jsonl").write_text(jsonl, encoding="utf-8")
    return {"digest": digest, "records": len(records)}


def load_corpus(digest: str) -> tuple[dict, list[dict]]:
    if not _DIGEST_RE.match(digest):
        raise ValueError("bad digest")
    path = corpora_dir() / f"{digest}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"corpus {digest} not shipped")
    return parse_corpus(path.read_text(encoding="utf-8"))


# Replay weights: how many times a record appears in the training stream.
# Human-anchored signals dominate merely-clean synthetic turns - the corpus is
# mostly model-generated text, and uniform replay of your own output is the
# silent-collapse recipe (Karpathy/Dwarkesh 2025-10; arXiv:2606.03979 keeps
# consolidation anchored on replay of *selected* memories for the same reason).
_SIGNAL_WEIGHT = {"hitl_approved": 3, "superseded": 2, "eval_pass": 2, "clean_run": 1}
_RECENT_SECONDS = 7 * 24 * 3600  # consolidation replays the recent past harder
_RECENT_FACTOR = 2


def _replay_weight(record: dict, now: float) -> int:
    weight = _SIGNAL_WEIGHT.get(str(record.get("signal")), 1)
    created = record.get("created_at")
    if created:
        try:
            age = now - datetime.fromisoformat(created).timestamp()
            if 0 <= age <= _RECENT_SECONDS:
                weight *= _RECENT_FACTOR
        except (TypeError, ValueError):
            pass
    return weight


def _chat_rows(
    records: list[dict], held_out: set[str], now: float
) -> list[tuple[dict, int]]:
    """(row, replay_weight) pairs from the trainable records, excluding the
    held-out set. The weight (signal quality x recency) is applied to the
    TRAIN side only - the valid split stays one-copy-per-example, and the two
    sides are split by EXAMPLE before any repetition, so no example's copies
    can straddle the boundary and flatter the validation loss.

    pref records contribute their CHOSEN side as an sft row (the rejected side
    is not trained on in this first cut - a DPO leg is a later, separate
    decision, and silently approximating one here would misreport what the
    adapter learned)."""
    rows: list[tuple[dict, int]] = []
    for r in records:
        if r["record_id"] in held_out:
            continue
        completion = r.get("completion") if r["kind"] == "sft" else r.get("chosen")
        if not completion:
            continue
        messages = [
            {"role": role, "content": content} for role, content in r["prompt"]
        ]
        messages.append({"role": "assistant", "content": completion})
        rows.append(({"messages": messages}, _replay_weight(r, now)))
    return rows


_TRAIN_LOCK = threading.Lock()  # one train at a time: shared data dirs + one GPU


def run_train(body: dict) -> tuple[int, dict]:
    if not _TRAIN_LOCK.acquire(blocking=False):
        return 409, {"error": "a training run is already in progress"}
    try:
        return _run_train_locked(body)
    finally:
        _TRAIN_LOCK.release()


def _run_train_locked(body: dict) -> tuple[int, dict]:
    digest = str(body.get("corpus_digest") or "")
    kind = str(body.get("adapter_kind") or "")
    base_pin = str(body.get("base_pin") or "")
    if kind not in _TRAIN_ARGS:
        return 400, {"error": f"unknown adapter_kind '{kind}'"}
    try:
        header, records = load_corpus(digest)
    except (ValueError, FileNotFoundError) as exc:
        return 404 if isinstance(exc, FileNotFoundError) else 400, {"error": str(exc)}
    if header.get("base_pin") != base_pin:
        # DIS-4, server side: the corpus was derived against one pin; training
        # it from any other base is refused, not adapted.
        return 409, {"error": "corpus base_pin does not match the requested base_pin"}
    if not mlx_available():
        return 503, {"error": "mlx_lm is not installed in BOLTRIG_DISTILL_MLX_PYTHON"}

    weighted = _chat_rows(records, set(header.get("held_out") or []), time.time())
    if len(weighted) < _MIN_TRAINABLE:
        return 400, {"error": f"corpus has {len(weighted)} trainable records; "
                              f"at least {_MIN_TRAINABLE} are needed"}
    adapter_id = f"{kind}-{digest[:12]}"
    adapter_path = adapters_dir() / adapter_id
    data_dir = STATE_DIR / "train" / adapter_id
    data_dir.mkdir(parents=True, exist_ok=True)
    # mlx_lm.lora expects train.jsonl/valid.jsonl in one data dir, and each
    # side must hold at least one full batch. Split by EXAMPLE first; only the
    # train side is then expanded by replay weight (see _chat_rows).
    split = max(_BATCH, len(weighted) // 10)
    _write_rows(data_dir / "valid.jsonl", [row for row, _ in weighted[:split]])
    _write_rows(
        data_dir / "train.jsonl",
        [row for row, weight in weighted[split:] for _ in range(weight)],
    )
    model_repo = base_pin.split("@", 1)[0]
    cmd = [
        MLX_PYTHON, "-m", "mlx_lm", "lora", "--train",
        # the BARE base - never a prior adapter; mlx's --resume-adapter-file
        # exists and is deliberately never passed (DIS-4)
        "--model", model_repo,
        "--data", str(data_dir),
        "--adapter-path", str(adapter_path),
        "--batch-size", str(_BATCH),
        *_TRAIN_ARGS[kind],
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return 500, {"error": "training failed", "stderr": proc.stderr[-4000:]}
    meta = {"adapter_id": adapter_id, "base_pin": base_pin,
            "corpus_digest": digest, "adapter_kind": kind}
    (adapter_path / "boltrig.json").write_text(json.dumps(meta), encoding="utf-8")
    return 200, meta


def _held_out_eval_file(digest: str) -> tuple[Path, int] | tuple[int, dict]:
    """Materialise the held-out sft rows for a shipped corpus, or an error."""
    try:
        header, records = load_corpus(digest)
    except (ValueError, FileNotFoundError) as exc:
        return 404 if isinstance(exc, FileNotFoundError) else 400, {"error": str(exc)}
    held = set(header.get("held_out") or [])
    rows = [r for r in records if r["record_id"] in held and r["kind"] == "sft"]
    if not rows:
        return 400, {"error": "corpus has no held-out records to score"}
    eval_file = STATE_DIR / "eval" / f"{digest}.jsonl"
    eval_file.parent.mkdir(parents=True, exist_ok=True)
    _write_rows(eval_file, rows)
    return eval_file, len(rows)


_MODEL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@/-]*$")


def _model_args(digest: str, model: str) -> list[str]:
    """Resolve a gate 'model' name: a trained candidate (base + adapter dir)
    or the incumbent (an explicit repo name, else the corpus's bare base).

    The adapter-dir lookup is confined to adapters_dir(): a crafted name must
    not escape it (defence in depth - the kernel schemas also constrain the
    charset, but this server enforces its own boundary)."""
    if not _MODEL_NAME_RE.match(model) or ".." in model:
        raise ValueError(f"refused model name {model!r}")
    header, _ = load_corpus(digest)
    base_repo = str(header.get("base_pin") or "").split("@", 1)[0]
    adapter_path = (adapters_dir() / model).resolve()
    if adapter_path.is_relative_to(adapters_dir().resolve()) and adapter_path.is_dir():
        return ["--model", base_repo, "--adapter", str(adapter_path)]
    return ["--model", model if "/" in model else base_repo]


def _run_scorer(script: str, digest: str, model: str, extra: list[str]) -> tuple[int, dict]:
    if not mlx_available():
        return 503, {"error": "mlx_lm is not installed in BOLTRIG_DISTILL_MLX_PYTHON"}
    located = _held_out_eval_file(digest)
    if isinstance(located[0], int):
        return located  # type: ignore[return-value]
    eval_file, count = located
    try:
        model_args = _model_args(digest, model)
    except ValueError as exc:
        return 400, {"error": str(exc)}
    cmd = [MLX_PYTHON, str(Path(__file__).parent / script),
           "--data", str(eval_file), *model_args, *extra]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return 500, {"error": "scoring failed", "stderr": proc.stderr[-4000:]}
    try:
        value = float(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return 500, {"error": "scorer returned no value"}
    return 200, {"model": model, "value": value, "held_out": count}


def run_loglik(body: dict) -> tuple[int, dict]:
    digest = str(body.get("corpus_digest") or "")
    model = str(body.get("model") or "")
    code, out = _run_scorer("mlx_score.py", digest, model, [])
    if code == 200:
        out = {"model": model, "mean_loglik": out["value"], "held_out": out["held_out"]}
    return code, out


def run_diversity(body: dict) -> tuple[int, dict]:
    """Distinct-2 over sampled generations for the held-out prompts, seeded
    from the corpus digest so a gate re-run samples the same generations."""
    digest = str(body.get("corpus_digest") or "")
    model = str(body.get("model") or "")
    seed = int(digest[:8], 16) if _DIGEST_RE.match(digest) else 0
    code, out = _run_scorer("mlx_diversity.py", digest, model, ["--seed", str(seed)])
    if code == 200:
        out = {"model": model, "distinct_2": out["value"], "held_out": out["held_out"]}
    return code, out


def _write_rows(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
    )


class Handler(BaseHTTPRequestHandler):
    server_version = "boltrig-distill-sidecar/0.1"

    def _reply(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > _MAX_BODY:
            raise ValueError("missing or oversized body")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self) -> None:  # noqa: N802 (http.server contract)
        if self.path == "/health":
            self._reply(200, {"status": "ok", "mlx": mlx_available()})
        else:
            self._reply(404, {"error": "not found"})

    def do_PUT(self) -> None:  # noqa: N802
        if not self.path.startswith("/corpus/"):
            self._reply(404, {"error": "not found"})
            return
        try:
            body = self._body()
            self._reply(200, store_corpus(self.path[len("/corpus/"):],
                                          str(body.get("jsonl") or "")))
        except ValueError as exc:
            self._reply(400, {"error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802
        try:
            body = self._body()
        except ValueError as exc:
            self._reply(400, {"error": str(exc)})
            return
        if self.path == "/train":
            self._reply(*run_train(body))
        elif self.path == "/loglik":
            self._reply(*run_loglik(body))
        elif self.path == "/diversity":
            self._reply(*run_diversity(body))
        else:
            self._reply(404, {"error": "not found"})

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write(f"{self.address_string()} {fmt % args}\n")


def main() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((BIND, PORT), Handler)
    sys.stderr.write(f"distill sidecar on {BIND}:{PORT}, state={STATE_DIR}\n")
    server.serve_forever()


if __name__ == "__main__":
    main()
