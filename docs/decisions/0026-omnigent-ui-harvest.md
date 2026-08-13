# 0026 - Harvest Omnigent's UI choreography without adopting its runtime

- Status: accepted (2026-08-12)
- Authority: principal direction in the 2026-08-12 Boltrig console task
- Reference revision: `omnigent-ai/omnigent@0bea9873e6b697290e0a2d172eb879151839a2a6`
- Delivery plan: `docs/proposals/omnigent-ui-harvest.md`

## Context

Omnigent has a mature coding-session information architecture: a calm task
hierarchy, a deep composer, chronological activity blocks, stable transcript
navigation, queued instructions, workspace panels, subagent views and
cross-device collaboration. Those interaction patterns are useful to Boltrig.

Its execution architecture is not. Omnigent is intentionally a multi-harness
runtime with runner-local and server-side tool paths and policy at server,
agent and session levels. Boltrig is intentionally Codex-only and requires
every external action to enter one ordered kernel dispatcher. Making Omnigent
the application base would create two authorities for execution, approvals,
credentials, event reduction, model selection and audit.

## Decision

Boltrig will implement Omnigent-inspired information architecture and
interaction choreography as Boltrig-native components over the existing web
SDK and governed kernel contracts.

The visual identity remains Boltrig's:

- one continuous canvas;
- borderless glass left rail and floating task inspector;
- Familiar identity and consequence-aware state;
- compact task rows and natural-language activity receipts;
- exact Bifrost model names;
- no duplicate Recents search field, workspace fixture identity, footer health
  row, conversation-title editor or governance marketing copy.

The kernel, SDK event vocabulary, normalizer, stores, policy authority and
credential boundaries remain authoritative. No Omnigent server, runner, chat
store, reducer, policy engine or direct filesystem/terminal path becomes a
Boltrig dependency.

## Reuse policy

Prefer behavior-level reimplementation and Boltrig-native tests. An isolated
source-level reuse requires a per-file dependency review and the Apache-2.0
notice and modification obligations to be recorded before it lands. Omnigent
brand assets and its mascot are not reused.

## Consequences

- Existing-contract UI work ships first: shell, transcript, queue, activity,
  artifacts, subagents, approvals, sources and model choice.
- Files, Git diff and process panels ship only after bounded verbs exist behind
  the normal dispatcher.
- An interactive terminal needs a separate decision covering session leases,
  approval, redaction, bounds and revocation. A raw browser-to-shell channel is
  refused.
- Presence, shared driving and comments remain a separate tenant-ACL and privacy
  project rather than decorative UI in this migration.
- The migration is a component-level strangler over unchanged task identities
  and persisted conversations, not a data or backend fork. Worker has one
  renderer and no feature-flag service, so a pretend `shell-v2` boolean is not
  added. Versioned presentation preferences remain downgrade-readable, while
  the extracted component boundaries and source-bound evidence are the
  rollback and rollout seams.
