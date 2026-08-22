# Data and storage: what lives where, and what leaves the computer

Boltrig is a hosted product with a desktop client. This page answers the
question every serious user asks in one form or another: "does the app have
its own database, and what actually leaves my computer?" It is written against
the code as of 2026-08-22 and should be corrected when the code moves.

The short answer is "yes internally, no as a product feature". The desktop app
keeps local state for its own operation; it does not ship a database for your
data. Your Boltrig data lives on a Boltrig server, and the desktop app is a
client of that server.

## 1. The desktop app's own local storage

The installed desktop app (Boltrig Worker, `apps/worker`, Tauri) maintains
local state, including:

- A per-computer identity key and your local approval posture, stored in the
  operating-system keychain (`src-tauri/src/device_roots.rs`,
  `session.rs`).
- Local task thread ids and metadata for tasks started in the app.
- Transcripts of local tasks, kept in the app's own browser-style storage on
  the machine with a fixed size cap (`src/localAgentClient.ts`:
  `MAX_STORED_BYTES`, `MAX_CONVERSATIONS`, `MAX_MESSAGES`).
- The bundled local agent runtime, a pinned and checksum-verified Codex CLI
  (`src-tauri/src/local_agent.rs`, `REQUIRED_RELEASE_CODEX_VERSION`), which
  keeps its own state in its own home directory on the computer: a small
  SQLite state database, optional session history, configuration, its
  sign-in, and optional local memories.
- Ordinary operating-system caches, logs, and application preferences.

None of this is a general-purpose database. It is internal implementation
detail, its layout is not stable or public, and it is not intended to hold
your application's data.

## 2. Your Boltrig data lives on the server

Everything durable in Boltrig is stored by the Boltrig server the app is
packaged against, in that server's tenant-scoped PostgreSQL database:
conversations, messages with their tool events and attachments
(`conversations`, `conversation_messages`), memory (`memory_*`), knowledge
uploads and documents (`knowledge_*` plus a server-side vault), artifacts,
settings, integrations, routines, approvals, and the hash-chained audit
record (`audit_log`). The schema is `boltrig/store/schema.sql`. The desktop
app has no copy and cannot work without a server; it shows "No Boltrig
server configured" if packaged without one.

Who owns that database depends on who runs the server. Hosted Boltrig means
Boltrig runs it. A self-hosted Boltrig (the compose stack, `genesis.sh`)
means you run it.

If you ask Boltrig to build an application, that application's database
belongs to the application, not to Boltrig. A SQLite file in a bound folder
is just a file in that folder. A hosted PostgreSQL, D1 or Supabase database
belongs to whichever provider you configured. Boltrig can write migrations,
schema, seed data and database code; it does not provide your application
with a durable backend database.

## 3. What "local task" and "bound folder" mean

A task started in the browser is a cloud task. A task started in the signed
desktop app is a local task whose agent runtime and shell execution live on
your computer (decision 0027). Local folders, shell and background work stay
disabled until you explicitly bind a folder in Settings, Advanced.

For a local task, the following remain on your machine: source files, git
metadata, local database files, build artifacts, dependency caches, local
logs, uncommitted changes, and local development services.

"Local" does not mean "never seen by the model provider". Local tasks run the
bundled Codex runtime under your own Codex/OpenAI sign-in. To produce an
answer it may send that provider your prompt, instructions from files such as
`AGENTS.md`, source excerpts it reads, files you attach, shell commands and
their outputs, test and build logs, diffs and proposed changes, and local
memory content if you have enabled it. The whole folder is not uploaded
merely because you bound it, but anything the agent reads, prints, attaches,
summarises or includes in a result should be treated as potentially leaving
your computer.

Boltrig never passes its own server credentials or provider keys into the
local runtime: the child process starts from an empty environment and
receives only a short allow-list (`SAFE_LOCAL_AGENT_ENVIRONMENT`), and the
test `local_agent_environment_never_delegates_shell_or_cloud_credentials`
pins that. The local shell is a boundary around your computer, not a new
integration.

## 4. What happens in a cloud task

A cloud task is materially different. The request goes to the Boltrig server
(`POST /v1/chat`), which runs the hosted agent fleet, routes model calls
through the provider configured for your workspace (bring-your-own-key is
supported, via the model gateway), resolves tools, credentials, integrations,
approvals and budget, and records the result. Each hosted run executes in a
fresh, per-run sandbox cell (own uid, private 0700 slot; see
`boltrig/fleet/infrastructure/codex_cell_provisioning.py`), not in a
persistent machine per agent. The conversation, its tool events, any
attachments and the audit trail are stored server-side. A cloud task cannot
touch your bound folder, and a local task is never silently sent to the
cloud; local unavailability is shown, not worked around.

Nothing moves between the two surfaces automatically. A transcript or file
produced in one does not appear in the other unless you move it.

## 5. What is stored by the Boltrig server

Three separate concepts are easy to mix up:

- Processing. The model provider processes what is sent during a turn. For
  cloud tasks that is the provider your workspace configured, reached through
  the Boltrig server. For local tasks it is OpenAI, reached directly by your
  own Codex sign-in.
- Storage. Conversations, memory, knowledge, artifacts, settings and audit
  are stored by the Boltrig server. Deleting a conversation closes it; a
  restore window applies; closed conversations are purged by a retention job
  (`boltrig/fleet/retention.py`, 30 days by default). The audit record is
  hash-chained and is deliberately exempt from purge. A personal export
  endpoint exists (`/v1/me/export`).
- Training. Boltrig does not use your content to train models. Whether a
  model provider may do so is governed by that provider's own account and
  workspace settings, separately for the cloud provider you configured and
  for your own OpenAI/Codex account used by local tasks.

Deleting a local file does not delete a server conversation that already
contains excerpts or outputs from it, and closing a conversation does not
remove what a provider already processed.

## 6. Boltrig memory versus Codex local memory

Boltrig can have two memory systems in play:

- Boltrig memory, held by the Boltrig server, scoped to you (or your
  department or organisation), written and read only through governed memory
  operations (`memory.*` verbs, decision 0029), and covered by its own erasure
  record (`memory_erasures`).
- Codex local memories, stored in the local runtime's home directory on your
  computer if you have turned them on, used by local tasks only.

They are separate and do not synchronise. If local memories are injected into
a later local task, their contents become model context and are sent to
OpenAI. Review those files before sharing that directory; do not rely on
automatic redaction.

## 7. Practical security recommendations

Treat Boltrig like a remote engineering assistant with optional local
execution, not like an offline program.

- Keep production credentials out of bound folders and repositories. Add
  `.env`, database dumps, backups and local database files to `.gitignore`.
- Use a sanitised development database and least-privilege credentials.
- Never ask the agent to print secrets or production customer records.
- Bind only the folders a task needs; unbind when finished.
- Understand the two data paths: cloud tasks use the provider your workspace
  configured; local tasks use your own OpenAI/Codex account. They are
  governed by different settings and policies.
- Disable Codex local memories and local history persistence if you do not
  want persistent local summaries or transcripts; this does not affect what
  the Boltrig server stores.
- Prefer local tasks for sensitive development while remembering that local
  tasks still send the context they use to the provider.
- Do not connect the agent to a production database unless you fully
  understand the permissions and data flow.
- If data must never leave the computer at all, hosted Boltrig is not the
  right architecture. You would need a self-hosted Boltrig server and a
  genuinely local model behind it.

## The final distinction

- The Boltrig desktop app has internal local state, including the bundled
  local runtime's own SQLite database.
- Boltrig does not give your application a managed database.
- Your Boltrig data (conversations, memory, knowledge, files, settings,
  audit) lives on the Boltrig server, hosted or self-hosted; the desktop app
  holds no copy.
- Your bound folders stay on your machine unless read, attached or included
  in a result.
- Local tasks still send used context to OpenAI under your own sign-in; cloud
  tasks send it to the provider your workspace configured, via the Boltrig
  server.
- The Boltrig server separately stores conversations, memory, uploads and
  account data according to its controls, with deletion, retention, export,
  and an audit record that survives purge.
