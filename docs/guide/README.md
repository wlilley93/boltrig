# Boltrig admin guide

Task-oriented onboarding for a tenant admin standing up and running a Boltrig box. Read in order, or jump to what you need.

1. [Getting started](00-getting-started.md) - what Boltrig is, standing up a box with `bash genesis.sh dev` (phases, inputs, the password floor), and logging in.
2. [Organisations and workspaces](01-organisations-and-workspaces.md) - the org (tenant) and workspace model, the role vocabularies and grant ceilings, creating workspaces, managing members, and switching the active workspace.
3. [Users and invites](02-users-and-invites.md) - invite-only login, inviting a user (org / workspace scoped, with provisioning), accepting an invite, the privilege ceiling, and deactivation.
4. [AI keys and models](03-ai-keys-and-models.md) - the org/workspace/user key hierarchy, `allow_own_ai_keys`, the sealed-storage guarantee, and provider/model routing including the SEC-12 sensitive-stays-local rule.
5. [Audit and compliance](04-audit-and-compliance.md) - the tamper-evident hash-chained audit, the SecurityEvent stream, the rollup anchor (and the Principal-gated external-anchoring seam), and how to search and verify.
6. [Security model](05-security-model.md) - the one-page trust model for a security reviewer: the dispatch chokepoint, deny-by-default grants, sealed credentials, the HITL gate, session + CSRF, edge-auth options, and what is not-yet-wired (2FA enforcement, external audit anchoring).

All route examples assume the console at `http://localhost:8080` (the `UI_PORT`). Mutating requests over a first-party session must echo the `boltrig_csrf` cookie in the `x-boltrig-csrf` header.
