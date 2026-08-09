# The parts of boltrig that run on the Mac, not in a container

Everything else in this repo runs in the OrbStack Linux machine `boltrig-vm`
(see `docker-compose.vm.yml` and decision 0022's handover). Three things cannot,
and this directory is where their launchers live so they are versioned like the
rest of the stack.

**The reason is always Metal.** mlx and whisper.cpp are fast on this box because
of the GPU, and Metal does not exist inside the Linux VM. A container would run
them on CPU and lose the property that made them usable. So they run natively,
bound to loopback (or, for whisper, to an address the VM can reach), and the
kernel treats them as ordinary outbound adapters.

| launchd label | runner | port | what depends on it |
|---|---|---|---|
| `app.boltrig.whisper` | `run-whisper.sh` | 8910 | `voice.listen` (`boltrig/adapters/builtin/local_whisper.py`) |
| `app.boltrig.distill` | `run-distill-sidecar.sh` | 8930 | nightly LoRA consolidation (`services/distill_sidecar/`, decision 0023) |
| `app.boltrig.ui` | `../../run-ui-8080.sh` (repo root) | 8080 | the console behind the shared cloudflare tunnel |

`run-ui-8080.sh` stays at the repo root because the installed launchd job already
points there; it is versioned, just not in this directory.

## Install

launchd does not expand `~` or `$HOME`, so the plists carry absolute paths with
`CHANGEME` where the username goes:

    for job in app.boltrig.whisper app.boltrig.distill; do
      sed "s|CHANGEME|$USER|g" "$job.plist.example" > "$HOME/Library/LaunchAgents/$job.plist"
      launchctl unload "$HOME/Library/LaunchAgents/$job.plist" 2>/dev/null
      launchctl load   "$HOME/Library/LaunchAgents/$job.plist"
    done

Reloading restarts the service, so do it when a voice turn or a distill run is
not in flight. `launchctl list | grep boltrig` shows what is loaded.

## What is deliberately NOT here

- **The weights.** `ggml-small.en.bin` (~150MB) and the mlx venv live under
  `~/opbox-dev/`. `services/distill_sidecar/README.md` has the venv recipe; the
  whisper runner refuses to start with a named path when the model is missing.
- **`run-vm-relay.sh`** (launchd `app.opbox.vm-relay`), which publishes the VM's
  18000/5432/8088 on loopback. boltrig's console depends on it — macOS 26 Local
  Network Privacy blocks a launchd job from reaching the VM's local-network
  address directly, and OrbStack already holds that permission, so the hop is
  made by a container and handed to vite on 127.0.0.1. It is **owned by opbox**
  and serves several stacks, so it is not vendored here. It replaced an earlier
  boltrig-only `run-kernel-relay.sh`, which is retired.
- **Anything holding a credential.** `.secrets/` stays out of git.

## The drift this closes

Until 2026-08-10 these runners existed only in `~/opbox-dev/`, which is not a
git repository on any machine. The code that the nightly distillation and the
voice stack call was therefore unbacked: losing the box would have kept every
commit and lost the wiring that makes them run. If you edit a runner, edit it
**here** and reinstall — a change made only in the deployed copy is invisible to
every other machine and to the next person reading this repo.
