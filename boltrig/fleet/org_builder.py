"""Composition root for the flat named-agent roster and serving pump."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from boltrig.config.manifest import NamedAgentConfig, resolved_named_agents

from .agent_mailbox import AgentMailboxService
from .named_agent import NamedAgent
from .permanent_runtime_factories import named as named_runtime
from .pump_policy import DEFAULT_LEASE_SECONDS, DEFAULT_MAX_ATTEMPTS, DEFAULT_SPAWN_BUDGET

if TYPE_CHECKING:
    from boltrig.api.codex_execution import CodexExecutionStack
    from boltrig.config.manifest import FleetManifest

    from .pump import WorkPump
    from .spawn import Spawner


def build_org(
    kernel: Any,
    spawner: Spawner | Any,
    manifest: FleetManifest | None = None,
    *,
    executor: Any = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    codex_execution: CodexExecutionStack | None = None,
) -> WorkPump:
    """Build durable tier-1 peers plus their one-task ephemeral children."""
    from .pump import WorkPump

    if manifest is None:
        roster = (NamedAgentConfig(name="general", address="general", runtime="script"),)
        default_agent = "general"
    else:
        resolved = resolved_named_agents(manifest)
        roster = resolved.members
        default_agent = resolved.default

    agents: dict[str, Any] = {}
    for profile in roster:
        skills = [skill for skill in profile.supported_skills if "*" not in skill]
        runtime = named_runtime(spawner, manifest, profile) if manifest is not None else None
        agents[profile.address] = NamedAgent(
            profile.address,
            profile.name,
            skills,
            DEFAULT_SPAWN_BUDGET,
            spawner=spawner,
            runtime=runtime,
            store=kernel.store,
        )
    mailbox = AgentMailboxService(kernel.store, agents, events=kernel.events)
    return WorkPump(
        kernel,
        spawner,
        None,
        agents,
        executor,
        named_agents=agents,
        default_agent=default_agent,
        mailbox=mailbox,
        max_attempts=max_attempts,
        lease_seconds=lease_seconds,
        codex_execution=codex_execution,
    )
