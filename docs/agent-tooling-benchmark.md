# Agent tooling benchmark and adoption record

Status: implemented baseline, 2026-08-14.

## Source boundary

The locally supplied comparison snapshot identifies itself as proprietary,
unlicensed, and not for redistribution. It was used only as a black-box-style
clean-room requirements input: reviewers recorded capability names, architectural
patterns, and observable failure modes, then wrote Boltrig-native requirements
without retaining source expressions. Boltrig copied no code, prompt prose,
schemas, assets, or implementation details from it. This record compares only
high-level product capabilities and independently implements the ideas that fit
Boltrig's architecture. Any future contributor must repeat that boundary rather
than treating the local snapshot as a vendorable dependency.

## Measured breadth

The comparison describes roughly 40 named coding-agent tools. A clean offline
Boltrig boot currently registers 98 concrete verbs without an external MCP server.
The vendored broader-tenant surface contains 242 verbs across 20 namespaces:

- 143 are first-party or kernel-native rather than dynamically consumed MCP tools;
- 67 remain after excluding both consumed MCP tools and the administrative
  `control.*` plane;
- a single admitted Codex run can carry up to 128 exactly named kernel tools;
- external MCP servers can add reviewed verbs without changing the kernel.

These numbers are a capacity check, not an invitation to give every run everything.
Boltrig deliberately exposes only the task-selected intersection of tenant policy,
caller authority, and skill requirements. `FR-MCP-04` holds both sides: the shipped
catalogue cannot shrink below a broad-agent floor, and shipped skills cannot replace
selection with a blanket grant.

## Capability mapping

| Agent capability | Boltrig surface | Deliberate boundary |
| --- | --- | --- |
| File list/read/write | `device.file.list/read/write` | Explicit enrolled device, opaque root, relative path, signed lease, approval |
| Shell/PowerShell/REPL | `device.command.run` | No ambient shell; argv-only, root policy, signed lease |
| Browser and web | `browser.*`, `web.fetch` | Stack-owned browser state and manifest egress policy |
| Ask a user | `chat.ask_user` | Owner-scoped question lifecycle, not approval laundering |
| Tasks and teams | `work.list/get`, governed `control.work.*`, permanent fleet, execution ledger | Read access is workspace/department scoped; mutations keep the existing author and approval boundary |
| Planning and automation | governed workflows, schedules, triggers | Published workflow and exact trigger authority, not prompt-only plans |
| Skills | `skill.search/load/describe`, governed skill authoring | Versioned manifests and explicit tool selections |
| Memory and context | `memory.*`, `knowledge.*`, conversation continuity | Scoped retrieval and untrusted-data envelopes |
| MCP discovery/invocation | kernel MCP face plus governed external MCP lifecycle | Review before activation; every call returns through dispatch |
| Communication | channel, email, chat, calendar, document verbs | Kernel-held credentials and consequence/HITL policy |
| Diagnostics | browser doctor, platform/readiness receipts, run/audit evidence | Content-free operational evidence rather than raw host access |
| Structured results | vendor-neutral turn `output_schema`; pinned bounded phase-result schema/parser | Ordinary chat still returns conversational text unless its caller binds a schema |

## Ideas adopted now

- A fuller stable operating method: inspect before mutation, bound retrieval,
  deliberate capability selection, conservative file/code work, sourced research,
  bounded delegation, explicit long-lived work state, verification after effects,
  honest ambiguity, and outcome-first communication. The same method now reaches
  every composed agent tier as well as the separately attested Codex tool lane.
- Tool metadata is explicitly subordinate to the governing prompt. Third-party MCP
  descriptions are labelled as untrusted data before publication.
- High-consequence tools explain their approval posture in the model-facing
  description without inventing unsupported read-only/destructive/idempotent hints.
- Unknown external risk labels now fail closed to high consequence.
- The catalogue breadth and the absence of blanket shipped grants are regression
  tested as an invariant.
- Agents now have bounded `work.list` and `work.get` verbs, selected by the shipped
  decomposition skill; raw source payloads and execution results stay out of that
  projection, while all mutations remain on the existing governed `control.work.*`
  lifecycle.
- Creating pending Work is high consequence because the fleet can later claim and
  execute it. Browser, channel, and governed-control ingress stamp the caller's
  creation-time grant ceiling onto the durable item; execution also consults current
  identity policy, and model-created descendants inherit the original ceiling. A
  later promotion therefore cannot silently widen already-queued work.
- Stable prompt material stays separate from volatile task and environment facts,
  preserving attestation and prompt-cache reuse.
- Material changes receive an independent review lane when available, or an
  adversarial second pass over primary artifacts when they do not. Approval is
  explicitly one exact-call decision rather than reusable consent.

## Ideas already present

- Progressive ordering of the full granted tool offer by skill affinity, exact
  grants, consequence, and deterministic name.
- Typed, scoped memory with provenance and untrusted re-entry.
- Explicit work, phase, assignment, approval, queued-message, and result lifecycles.
- Bounded tool errors that name invalid keys without echoing values.
- Run-scoped MCP credentials, exact tool ceilings, and model-proxy enforcement.
- Structured tool/subagent/HITL events instead of parsing prose.
- Runtime skill discovery and progressive disclosure through
  `skill.search`/`skill.describe`/`skill.load`; skills are not limited to birth-time
  composition, and a loaded skill returns requested grants as data rather than
  widening the run.
- A vendor-neutral caller-supplied output-schema seam, plus a pinned, bounded,
  secret-screened phase-result document and parser. This is stronger than an
  unvalidated "final answer" convention, but it is not yet exposed as arbitrary
  user-authored structured output in ordinary Chat.

## Ideas not adopted

- Direct native filesystem, shell, network, plugin, or self-extension authority.
  Those would bypass the kernel and violate the threat model.
- A raw count-based blanket grant. Breadth belongs in the catalogue; selection
  belongs in the run.
- Runtime-generated system-prompt snapshots containing cwd, git, host, or clock
  values. Current facts come from governed reads so stale data cannot acquire
  system authority and the stable prefix remains cacheable.
- Copied proprietary prompts, assets, or source.
- Fixed word-count quotas for every inter-tool or final message. Brevity remains a
  goal, but the useful bound depends on consequence, evidence, and the user's task;
  a universal number would reward omission in the cases that most need precision.
- A blocking sleep tool. Durable schedules, workflow waits, and resumable work are
  safer than paying for an agent turn that merely holds a worker open.
- A prompt-only plan mode. Boltrig records plans as scoped Work and workflow state;
  an unrecorded mode flag would not create durable authority or progress. A future
  planning presentation may project that state without becoming a second control
  plane.
- A general REPL or ambient workspace filesystem. Code execution and host files
  stay behind an admitted cell or enrolled-device root instead of acquiring access
  from a convenient tool name.

## Honest remaining extensions

The following are category gaps even though the catalogue already exceeds the
comparison's raw count:

- Typed device-side content search and patch/edit, language-server diagnostics,
  and notebook-cell editing. They need bounded schemas, native executor support,
  signed lease actions, root/symlink tests, and cross-platform parity. Today some
  can be composed through `device.command.run`, but Boltrig does not pretend that a
  generic command is the same as a purpose-built, safely projectable verb.
- Governed web search. `web.fetch` retrieves a known URL; discovery should be a
  separate provider-backed adapter with query/result bounds, citation provenance,
  SSRF/egress policy, redacted credentials, and a declared consequence. It should
  not scrape through the fetch verb or silently depend on one operator's account.
- Arbitrary consumer-defined structured chat output. The runtime/schema machinery
  exists, but the Chat/API contract needs an authenticated bounded schema input,
  schema-complexity limits, exact persistence/audit binding, and a typed failure
  state before this can be advertised as a general capability.
- Registry-declared behavioural metadata such as read-only, destructive,
  idempotent, and concurrency-safe. Consequence is authoritative today; the other
  signals must be explicit closed fields with migration and adapter proofs rather
  than guesses derived from names. Only then should the model use them for call
  scheduling.
- Deferred schemas are a prompt-size optimisation, not authority. If the admitted
  offer grows enough to justify them, the discovery token must still be scoped to
  the exact run and schema retrieval must remain digest-bound to the advertised
  name; until measurements show pressure, deterministic ranked disclosure is the
  simpler contract.
