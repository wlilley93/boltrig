# Opbox prompt and profile harvest

Status: harvested 2026-07-04 for the pinned Boltrig transition.

These fixtures preserve Opbox agent behavior before replacing the current
Opbox/Hermes/Rivet agent surfaces with a pinned Boltrig host-agent facade.

They are app-owned prompt/profile material, not Boltrig engine doctrine. Keep the
generic Boltrig runtime header in `docs/prompts/runtime-agent.md`; compose these
fixtures after that header only when running Boltrig as the Opbox agent runtime.

## Sources

- `opbox-agent/runtime/src/loop.ts`: current governed agent loop system prompt,
  write-approval pause/resume wording, tool-use policy, function-call loop.
- `opbox-agent/runtime/src/server.ts`: release `agent-chat` API and SSE event
  names consumed by Opbox frontend.
- `opbox-agent/config.yaml.example`: Hermes cage/profile defaults.
- `opbox-agent/gateway/app.py` and `gateway/README.md`: dev/demo OpenAI and
  AG-UI compatibility behavior, model context override, caged-toolset handling.
- `opbox-frontend/src/lib/ai/system-prompt.ts`: legacy rich chat prompt
  behavior for tools, no-fabrication, page context, RAG-like referenced content,
  skills, UK English, and entity-card display.
- `opbox-agent/docs/handover-sso-identity-files.md`: structured object-reference
  requirement for MatterCard/form/document-style UI.

## Artifacts

- `opbox-host-agent-fixtures.yaml`: machine-readable prompt/profile fixtures.
- `golden-tasks.md`: behavioral comparisons that should pass before routing
  users to Boltrig.

## Migration Rule

Do not migrate only the transport. Migrate the agent contract:

- Opbox-specific system behavior.
- Opbox tool-use bias.
- Opbox write-approval semantics.
- Opbox cage/profile constraints.
- Opbox rich-context handling.
- Opbox object-reference rendering hooks.
- OpenAI/AG-UI compatibility details for live clients.

Prompt/profile revisions must be versioned separately from runtime and model
revisions so a model swap does not hide a prompt regression.
