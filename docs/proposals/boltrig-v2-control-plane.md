# Superseded control-plane proposal

Status: **RETIRED 2026-08-14**.

This pre-Codex proposal described a multi-runtime control plane that is no
longer part of Boltrig. The executable clients, plugins, binaries, state,
readiness checks, manifest defaults and deployment wiring for those alternative
runtimes have been removed.

The current architecture is:

- trusted Codex is the only model-backed agent runtime;
- deterministic script aliases remain for explicit non-model jobs;
- Bifrost owns model routing behind the trusted Codex boundary;
- Browser Use remains a governed browser-automation tool, not an agent runtime;
- Hatchet remains the optional durable workflow engine; and
- all actions still cross the kernel chokepoint.

See [the Codex integration map](codex-app-server-integration-map.md),
[the current engine catalogue](../architecture/engine-components.md), and
[the runtime retirement decision](../decisions/0020-retire-the-pi-lane.md).
