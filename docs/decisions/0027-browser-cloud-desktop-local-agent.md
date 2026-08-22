# 0027 - Browser cloud agent and desktop local agent

- Status: accepted
- Date: 2026-08-13
- Amends: 0012 (Codex ownership), 0017 (hosted Codex postures), and 0021
  (desktop device boundary)

## Context

Worker is one React surface with two materially different execution contexts.
A browser cannot own a local process, shell, or workspace. The signed Tauri
application can. Treating both builds as clients of the hosted Fleet made the
desktop app a thinner browser and incorrectly turned the hosted Codex admission
gate into a statement that "Codex is disabled" everywhere.

The product decision is instead:

> A task started in the browser is a cloud task. A task started in the signed
> app is a local task whose Codex runtime and Bash execution live on that
> computer.

This is a surface boundary, not an automatic failover. The app must never send a
local task to the cloud because its local runtime is missing, and the browser
must never imply that it can execute on the user's computer.

## Decision

Worker keeps one presentation and two explicit execution adapters.

### Browser: hosted cloud agent

- Browser chat uses the authenticated `/v1/chat` contract and the hosted Fleet.
- The kernel remains the authority for credentials, integrations, model routes,
  tools, approvals, audit, and durable cloud conversation state.
- A production web product requires the hosted-agent admission gate. A
  server-only `core` release is infrastructure evidence, not a usable Boltrig
  product release.

### Tauri: local agent

- Tauri starts a pinned Codex App Server child over private stdio. It does not
  expose a listener and does not scrape a terminal UI.
- The local thread runs in a folder the user explicitly bound to this enrolled
  desktop. The native path never crosses the browser/server contract.
- Codex owns the local reasoning loop and shell execution. Bash is part of that
  local execution substrate; it is not enabled on the cloud-issued
  `device.command.run` lease path.
- The app has its own device-side three-way posture. It is stored in the OS
  keychain and never inherits the account's cloud posture. `always_ask` and
  `risk_based` remain sandboxed and surface App Server approval requests to the
  user. `full_access` requires a second native confirmation and applies to
  subsequent local turns in that signed app; it does not widen server grants,
  expose a server credential, or make a cloud task local.
- Provider credentials, integrations, remote tools, cross-tenant data, and
  Boltrig control-plane mutations still enter through the kernel. A local shell
  does not receive kernel/provider secrets. Raw local shell access is therefore
  a user-owned computer boundary, not a new integration adapter.
- Local unavailability is typed and visible. No fallback to hosted Fleet,
  legacy runtimes, a remote device lease, or a personal Ollama host is allowed.

### Shared product identity

Familiar and Jarvis, plugins, the model catalogue, approval-posture labels, and
the visual shell remain shared presentation. Execution receipts must state
`cloud` or `local`; the two modes must not be visually indistinguishable in
technical diagnostics. Personal companions and operator-owned model hosts are
not release defaults.

### Account-first desktop bootstrap

User authentication is the front door for both surfaces. The hosted Worker may
show an authenticated link to the signed desktop distribution; the downloaded
app signs in to the same production account on startup. After authentication,
the desktop automatically consumes a short-lived server bootstrap to create its
revocable per-computer key in the OS keychain. Users never copy or paste an
enrollment code. The per-computer identity is retained underneath account auth
because it provides machine-specific revocation, signed lease verification and
opaque native-root ownership without putting those powers in a browser cookie.
Conflicting or unreadable local identity is never overwritten silently.

## Security and lifecycle constraints

1. Production desktop packages bundle and verify the supported Codex binary;
   release builds do not resolve an arbitrary executable from `PATH` or an
   environment variable. Development builds may use a local binary but must say
   that they are unbundled development runtime.
2. App Server uses bounded JSONL over stdio. Unknown server requests are denied,
   malformed/oversized frames terminate the local turn, and only the documented
   command/file approval responses are accepted.
3. A workspace is selected by opaque local root id. App Server receives the
   canonical native path internally; JavaScript and the server receive only the
   opaque id.
4. Local task metadata and thread ids are stored on that computer. Cloud task
   content remains server-owned. Cross-surface continuation requires an explicit
   future import/export contract; it is never inferred.
5. Closing, interrupting, switching, or crashing a local task terminates its
   active child or sends the correlated App Server interrupt. A stale process
   cannot continue under a newly selected task.

## Consequences

- The production Codex cell gate remains fail-closed for hosted Fleet until its
  separate attestation work is complete. That fact no longer describes the
  desktop local runtime.
- Decision 0021's sentence "not a local agent server" is superseded for the
  signed Tauri product. Its signed remote device-lease boundary remains intact
  and separate.
- Full product release requires hosted web-agent acceptance and signed desktop
  local-agent acceptance. `core` may exercise infrastructure only and must say
  that both user-facing agent surfaces are omitted.

## Rejected alternatives

- **Allow `bash -lc` in `device.command.run`.** That lease is cloud-issued,
  discards output, and has a different approval lifecycle. Enabling a shell
  there would create a remote side door without producing a usable local agent.
- **Silently route Tauri chat to `/v1/chat`.** This hides where work executes
  and defeats the local product decision.
- **Run a browser-accessible local HTTP agent.** Stdio keeps the process private
  to the signed app and avoids a new localhost authentication surface.
- **Ship the operator's M1/Ollama settings.** Local and BYO routes are user data,
  never release defaults.

## Amended 2026-08-22: app-private runtime home

- The bundled local runtime always runs with `CODEX_HOME` set to a directory
  the signed app owns: `<app data>/local-agent/codex-home`, created owner-only
  (`0700` on Unix) with a minimal `config.toml` seeded once and never
  overwritten. `CODEX_HOME` is never inherited from the environment and nothing
  is read from or copied out of a personal `~/.codex` (its `config.toml` with
  any provider or MCP overrides, `auth.json`, memories, history). A Finder- or
  Dock-launched app and a terminal-launched one therefore run the same runtime.
- Consequence for sign-in: the private home starts without a credential, so
  local tasks have no model access until the user signs the local runtime in
  from Settings → Advanced. The app runs the bundled binary's device-code login
  (`codex login --device-auth`) under the private home: the child prints the
  sign-in page and a one-time code, the app opens that HTTPS page (and only an
  `openai.com` page) in the system browser and shows the code, and the child
  polls until the user finishes or the code expires. Neither the app nor the
  child opens a local listener for this flow; the plain `codex login`, which
  binds `127.0.0.1:1455` for its browser callback and launches a browser on its
  own, is deliberately not used. Sign-out runs the binary's `logout` under the
  private home and removes `auth.json` there; it also cancels a sign-in still
  in progress. `LocalAgentStatus` carries `signed_in`, and a local turn refuses
  with `local_agent_not_signed_in` rather than letting the runtime fail later.
- What does not change: the local agent still acts on the user's own computer,
  in the bound folder, under the device-side posture of this decision. The
  sign-in is the user's own runtime account, kept on that computer; it is not a
  Boltrig or provider credential and is never sent to the kernel.
