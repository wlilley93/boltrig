# Definition of Done - Round Six (Pi runtime)

Spec: [`requirements-pi-runtime.md`](./requirements-pi-runtime.md). Scope: the
standalone Boltrig repo, the **pi runtime lane only**. The `hermes` and
`claude-api` lanes are single-shot, non-agentic, and untouched. The kernel needs
no rework; all three gaps were in the fleet layer.

The spec's repo-grounding claims were verified against the actual code before any
build (the spec itself flagged several as unconfirmed). Two findings shaped the
implementation: `PiRuntime` receives a **pre-resolved** endpoint (it does not
resolve at construction), so the gateway seam lives at the spawner's resolution
point, not in `PiRuntime`; and the sidecar egress restriction was **only
documented, never enforced** in the manifests.

## What shipped

### 3.1 Session continuity (gap is foundational - fixed first)

- `boltrig/fleet/continuity.py` (new): renders the already-persisted, owner-scoped
  conversation transcript into the task string before `spawn()`. The render is a
  plain per-message concatenation, so it is **deterministic** and **append-only**
  - turn N's render is a prefix of turn N+1's (the prefix stability the gateway
  cache relies on). Pure functions, imports only models (severable, SEC-28).
- `boltrig/fleet/chat.py`: `build_turn_executor` composes the transcript from the
  tenant- and conversation-scoped `list_messages` before the spawn. Because
  `handle_turn` persists the current user message first, the scoped read already
  returns the full ordered transcript ending in the current turn.
- Native, Store-backed, in-conventions (P1/P7), no new runtime - the spec's
  recommended path over Rivet Actors. On by default; `BOLTRIG_CONTINUITY=0`
  restores the exact prior single-message behaviour.
- **Decision (recorded):** building the spec's recommended option (native first)
  is implementation of a provided spec, not a first-impression fork, so no court
  was convened. Rivet remains the documented escalation if a concrete
  cross-process realtime need emerges that the Store seam cannot meet.

### 3.2 Model gateway (sequenced after 3.1)

- `boltrig/fleet/model_gateway.py` (new): a read-side seam only (no authorization
  role, P1). A TTL-bounded `conversation_id -> model` binding pins a conversation
  to one model across turns - keyed on the **conversation**, because `run_id` is
  minted fresh every turn and is the wrong cache key.
- `boltrig/fleet/spawn.py`: the spawner consults the binding at endpoint
  resolution and points `base_url` at the configured gateway. **Sensitive data is
  never re-routed** - it reaches its local endpoint directly (residency, SEC-43).
  Inert when `BOLTRIG_MODEL_GATEWAY_URL` is unset (behaviour identical to before).
- The gateway product itself (Bifrost or equivalent) is an external deployment;
  this is the seam + binding it attaches to.

### 3.3 Execution isolation (deferred build, egress hardened now)

- The spec recommends NOT adding a new sandbox substrate until a real
  third-party Pi loop replaces the first-party stand-in. Until then, harden what
  exists.
- `docker-compose.yml` + `deploy/compose.secure.yml`: the Pi sidecar now sits on
  a dedicated `sandbox` network **only** (it can reach the kernel MCP face, not
  postgres/redis/the rest), and the secure overlay flips `sandbox` to
  `internal: true` (no arbitrary internet egress). The egress restriction is now
  **enforced**, not just a comment.

## Invariants (binding-debt 0)

Four new, all bound (`tests/security/test_round_six.py`):

- **SEC-46** continuity is deterministic + append-only (prefix stable) and adds
  no authority.
- **SEC-47** the gateway binds per conversation (not run), pins one model across
  turns, and never re-routes sensitive data.
- **SEC-48** the sidecar's egress is enforced by the manifests (a manifest-lint
  test), not merely documented.
- **SEC-49** continuity is scope-safe - only the caller's own
  tenant/conversation history is ever composed.

## Gate (green)

- `pytest`: **113 passed, 14 skipped** (+5 over Round Five).
- `check_invariants.py`: **declared=68, marked=68, bound_tests=87,
  binding_debt=0, PASS**.
- `ruff check boltrig scripts`: clean.

## Honest seams (environmental, not code)

- The cost gateway itself (Bifrost) is undeployed; cache-hit-rate observability
  (sequencing step 4) lands when it is stood up. The binding store here is
  in-memory and per-spawner; the chat path uses one stable spawner across turns,
  so bindings persist where it matters. A durable cross-worker binding store is
  the follow-on when the gateway is actually deployed.
- The `internal: true` secure posture requires a local or proxied model (an
  external provider URL is unreachable by design from the sandbox). Documented in
  the compose comments.
- agentOS / a hard sandbox boundary is deferred until a real third-party Pi
  toolkit is adopted into the sidecar (the point "we wrote every line, so we know
  it has no tools" stops being true), per the spec's open item.

This closes the Pi runtime spec (gaps 3.1 and 3.2 built; 3.3 hardened with the
substrate swap deferred by design).
