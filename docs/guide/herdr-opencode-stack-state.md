# Herdr, OpenCode, and Browser CLI stack state

Boltrig v2 treats Herdr, OpenCode, and Browser Use CLI state as stack
components, not as mounted copies of an operator's personal terminal,
coding-agent, or browser profile. The kernel image ships a pinned Herdr CLI, and
the fleet-worker image ships pinned OpenCode and Browser Use CLIs.

The deployed stack must use clean service-owned state roots:

```env
BOLTRIG_HERDR_HOME=/var/lib/boltrig/herdr
BOLTRIG_OPENCODE_HOME=/var/lib/boltrig/opencode
BOLTRIG_FLEET_BROWSER_CLI_HOME=/var/lib/boltrig/browser-cli/fleet-worker
BOLTRIG_HATCHET_BROWSER_CLI_HOME=/var/lib/boltrig/browser-cli/hatchet-worker
```

Fleet and Hatchet run independent Chromium processes, so their roots must remain
different even when they share one deployment-owned named volume. In Docker
Compose these paths are backed by named volumes. The images create the
root, home, config, data, and state directories as the unprivileged `boltrig`
service user so fresh named volumes start writable by the service. Browser CLI
also gets a stack-owned cache directory. These roots are safe to persist because
they belong to this Boltrig deployment, not to a human user's `~/.config/herdr`,
`~/.local/share/herdr`, `~/.config/opencode`, project-local `.opencode`, or
Browser Use/Chrome profile directory.

Do not bind-mount personal Herdr/OpenCode/Browser CLI state into production.
Personal state can contain sessions, sockets, logs, local plugin configuration,
project paths, model-provider preferences, browser cookies, cloud browser auth,
and other operator-specific data. Boltrig should ship its own clean runtime
state, then inject only the scoped runtime environment it needs for each run.

The static production doctor checks this posture:

```bash
boltrig doctor --production --env-file .env --manifest manifest.yaml
```

The doctor fails production mode when a required root is unset, points at a
user-owned config/local state path, shares one directory between Herdr and
OpenCode, or the runtime cannot resolve stack-owned `herdr` / `opencode` /
`browser-use` CLI binaries. Compose supplies safe defaults at runtime, but
checked production env files and non-Compose deployments should set explicit
service-owned paths.

The Fleet entrypoint binds Browser Harness to the Chromium it starts on its own
loopback CDP endpoint. A headless image or server must never ask an operator to
approve Chrome remote debugging; that prompt means the process has fallen back
to desktop-browser discovery and the image must be rejected.

The binaries are image artefacts. Upgrade Herdr/OpenCode by changing the version
and sha256 build args in the Dockerfiles; upgrade Browser Use by changing
`deploy/browser-cli-requirements.in` and regenerating the hash-locked
`deploy/browser-cli-requirements.txt` with
`uv pip compile deploy/browser-cli-requirements.in --overrides deploy/browser-cli-overrides.txt --generate-hashes --python-platform linux -o deploy/browser-cli-requirements.txt`.
Rebuild the stack after either change. Production doctor verifies that
`browser-use` resolves from the deployed stack path before browser verbs are
considered ready.
Do not seed a server by copying `~/.local/bin/herdr`,
`~/.opencode/bin/opencode`, `~/.local/bin/browser-use`, or any operator config
directory from a workstation. Likewise, do not set `HERDR_BIN`,
`BOLTRIG_OPENCODE_BIN`, or `BOLTRIG_BROWSER_CLI_BIN` to paths under a developer
home directory.

Browser CLI child processes also receive a scrubbed environment, not the full
service environment. The adapter passes stack-owned `HOME`/XDG paths, a small
runtime allowlist, and adapter variables such as `BU_NAME`. It strips provider
keys and personal `BROWSER_USE_*` variables by default. Browser Use cloud
profiles are opt-in only:

```env
BOLTRIG_BROWSER_CLOUD_POLICY=stack
BOLTRIG_BROWSER_CLOUD_API_KEY=...
BOLTRIG_BROWSER_CLOUD_PROFILE_ID=...
```

Those `BOLTRIG_BROWSER_CLOUD_*` values are the only source mapped into the
`browser-use` child process. Keep the default `disabled` policy unless the
deployment has a stack-owned Browser Use cloud profile.

Herdr and OpenCode follow the same rule. Their child processes get only a small
runtime allowlist, stack-owned `HOME`/XDG paths, and explicit scoped handoffs
such as the per-run Boltrig MCP token for OpenCode. They do not inherit provider
keys, personal Herdr socket paths, `BOLTRIG_OPENCODE_HOME`, or other deployment
posture variables from the service environment.

The authenticated `GET /v1/platform/status` endpoint also exposes this posture
as redacted operator metadata. It names Herdr, OpenCode, and Browser CLI as
first-party image tools and reports whether their state and binary settings look
stack-owned, but it deliberately omits the actual state roots, binary paths,
browser auth/session contents, Browser Use cloud values, tokens, credentials,
and profile locations. That keeps the cockpit useful on a server deployment
without copying or disclosing a human user's local environment.
