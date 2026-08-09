# distill sidecar

The trainer/scorer half of sleep distillation (decision 0023,
`docs/proposals/sleep-distillation.md`). Runs **native on the Mac host** -
mlx needs Metal, and Metal does not exist inside the OrbStack VM (the whisper
precedent, `boltrig/adapters/builtin/local_whisper.py`). The kernel's
`distill` adapter reaches it at `http://host.orb.internal:8930` through the
egress guard's documented `allow_internal` opt-in.

`app.py` is stdlib-only; mlx-lm runs as a subprocess in its own venv, so a
missing install answers 503 rather than crashing the service.

## Setup (M4)

```sh
# 1. an mlx venv, separate from the repo venv
uv venv ~/opbox-dev/mlx-venv --python 3.12
~/opbox-dev/mlx-venv/bin/pip install mlx-lm

# 2. run the sidecar
BOLTRIG_DISTILL_MLX_PYTHON=~/opbox-dev/mlx-venv/bin/python \
  python3 services/distill_sidecar/app.py
```

For boot persistence copy `app.boltrig.distill.plist.example` to
`~/Library/LaunchAgents/app.boltrig.distill.plist`, fix the paths, and
`launchctl load` it (the `app.boltrig.whisper` pattern). Remember the macOS
local-network privacy trap: a launchd job that must reach LAN addresses needs
the loopback relay - this sidecar only ever *listens*, so it is unaffected.

## Serving a promoted adapter

`mlx_lm.server` speaks OpenAI-shaped chat completions:

```sh
~/opbox-dev/mlx-venv/bin/python -m mlx_lm server \
  --model mlx-community/Qwen2.5-7B-Instruct-4bit \
  --adapter-path ~/.local/state/boltrig-distill/adapters/craft-<digest12> \
  --port 8931
```

and the promoted `ModelEndpoint` points its `base_url` at
`http://host.orb.internal:8931/v1` (`kind: openai`, `data_class: sensitive`).

## Contract notes

- `PUT /corpus/{digest}` refuses a body whose header digest differs.
- `POST /train` refuses a corpus whose `base_pin` differs from the request's
  (DIS-4's server half) and always trains from the **bare base** - no request
  field can name a prior adapter.
- Held-out records never train (they are the register gate's scoring set).
- `POST /loglik` scores ONLY the held-out split, teacher-forced, no sampling.

## Smoke

```sh
curl -s localhost:8930/health
# {"status": "ok", "mlx": true}
```
