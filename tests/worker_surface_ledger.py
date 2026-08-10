"""Exact backend-to-Worker surface declarations for the primary UI.

This is deliberately data rather than route-prefix heuristics. A new backend
route must name the SDK method and Worker source that operates it, or receive an
explicit non-UI classification with a documented boundary.
"""

from __future__ import annotations

from dataclasses import dataclass


Route = tuple[str, str]


@dataclass(frozen=True)
class WorkerSurface:
    sdk_method: str
    source: str


@dataclass(frozen=True)
class IndirectWorkerSurface:
    sdk_method: str
    replacement_method: str
    source: str
    rationale: str


WORKER_ROUTES: dict[Route, WorkerSurface] = {}


def _surface(source: str, declarations: str) -> None:
    for declaration in declarations.strip().splitlines():
        method, path, sdk_method = declaration.split()
        route = (method, path)
        if route in WORKER_ROUTES:
            raise ValueError(f"duplicate Worker route declaration: {route}")
        WORKER_ROUTES[route] = WorkerSurface(sdk_method=sdk_method, source=source)


_surface(
    "apps/worker/src/App.tsx",
    """
GET /v1/conversations conversationsPage
""",
)
_surface(
    "apps/worker/src/components/Shell.tsx",
    """
GET /v1/conversations/search searchConversations
""",
)
_surface(
    "apps/worker/src/components/settings/SpendingSection.tsx",
    """
GET /v1/cost cost
""",
)
_surface(
    "apps/worker/src/components/CommandPalette.tsx",
    """
POST /v1/search federatedSearch
""",
)
_surface(
    "apps/worker/src/components/ChatView.tsx",
    """
GET /v1/conversations/{conversation_id} conversation
GET /v1/conversations/{conversation_id}/events followConversation
POST /v1/chat streamChat
GET /v1/chat/config chatConfig
GET /v1/familiar/phenotype familiarPhenotype
GET /v1/model-profiles modelProfiles
GET /v1/artifacts artifacts
GET /v1/artifacts/{artifact_id}/download downloadArtifact
""",
)
_surface(
    "apps/worker/src/components/ConversationControls.tsx",
    """
DELETE /v1/me/conversations/{conversation_id} deleteMyConversation
PATCH /v1/me/conversations/{conversation_id} renameConversation
POST /v1/me/conversations/{conversation_id}/messages/{message_id}/regenerate regenerateMessage
POST /v1/me/conversations/{conversation_id}/restore restoreMyConversation
""",
)
_surface(
    "apps/worker/src/components/AccountView.tsx",
    """
GET /v1/me/settings meSettings
""",
)
_surface(
    "apps/worker/src/components/AccountProfileSections.tsx",
    """
PUT /v1/me/settings putMeSettings
GET /v1/me/activity meActivity
GET /v1/me/export meExport
GET /v1/privacy/policy privacyPolicy
""",
)
_surface(
    "apps/worker/src/components/AccountSecuritySections.tsx",
    """
GET /v1/me/tokens meTokens
POST /v1/me/tokens mintToken
DELETE /v1/me/tokens/{token_id} revokeToken
GET /v1/me/sessions meSessions
DELETE /v1/me/sessions/{session_id} revokeSession
POST /v1/me/active-context switchActiveContext
POST /v1/me/active-org switchActiveOrg
GET /v1/me/orgs myOrganisations
""",
)
_surface(
    "apps/worker/src/components/AccountAutomationSections.tsx",
    """
GET /v1/me/notifications meNotifications
PUT /v1/me/notifications putMeNotification
POST /v1/me/notifications/{preference_id}/test testMeNotification
GET /v1/me/agent meAgent
POST /v1/me/agent configurePersonalAgent
DELETE /v1/me/agent deletePersonalAgent
POST /v1/me/agent/invoke invokePersonalAgent
""",
)
_surface(
    "apps/worker/src/components/ConnectionInstructions.tsx",
    """
GET /v1/me/connections meConnections
""",
)
_surface(
    "apps/worker/src/components/AiKeyManagement.tsx",
    """
GET /v1/ai-keys aiKeys
PUT /v1/ai-keys setAiKey
GET /v1/ai-keys/proposals aiKeyProposals
GET /v1/ai-keys/proposals/{proposal_id} aiKeyProposal
POST /v1/ai-keys/proposals/{proposal_id}/finalize finalizeAiKeyProposal
DELETE /v1/ai-keys/proposals/{proposal_id} invalidateAiKeyProposal
DELETE /v1/ai-keys/{level}/{scope_id} deleteAiKey
""",
)
_surface(
    "apps/worker/src/components/AuthGate.tsx",
    """
POST /v1/auth/login login
POST /v1/auth/password-reset/request requestPasswordReset
POST /v1/auth/password-reset/confirm confirmPasswordReset
POST /v1/auth/2fa/challenge twoFactorChallenge
POST /v1/auth/accept-invite acceptInvite
POST /v1/auth/2fa/enroll twoFactorEnrollBegin
POST /v1/auth/2fa/verify-enroll twoFactorVerifyEnroll
POST /v1/auth/change-password changePassword
POST /v1/auth/refresh refreshSession
""",
)
_surface(
    "apps/worker/src/components/AccountSecuritySections.tsx",
    """
POST /v1/auth/2fa/disable twoFactorDisable
""",
)
_surface(
    "apps/worker/src/components/Views.tsx",
    """
POST /v1/auth/logout logout
""",
)
_surface(
    "apps/worker/src/components/OrganisationView.tsx",
    """
GET /v1/orgs/current currentOrg
""",
)
_surface(
    "apps/worker/src/components/OrganisationDirectorySections.tsx",
    """
GET /v1/orgs/current/members orgMembers
GET /v1/admin/users adminUsers
PATCH /v1/admin/users/{user_id} patchUser
GET /v1/admin/invitations adminInvitations
POST /v1/admin/invitations createInvitation
DELETE /v1/admin/invitations/{invite_id} revokeInvitation
""",
)
_surface(
    "apps/worker/src/components/OrganisationWorkspaceSections.tsx",
    """
PATCH /v1/orgs/current updateCurrentOrg
GET /v1/workspaces workspaces
POST /v1/workspaces createWorkspace
PATCH /v1/workspaces/{workspace_id} updateWorkspace
GET /v1/workspaces/{workspace_id}/members workspaceMembers
POST /v1/workspaces/{workspace_id}/members addWorkspaceMember
DELETE /v1/workspaces/{workspace_id}/members/{user_id} removeWorkspaceMember
""",
)
_surface(
    "apps/worker/src/components/OperationsView.tsx",
    """
GET /readyz readiness
GET /v1/console/overview consoleOverview
GET /v1/platform/status platformStatus
GET /v1/birth-profile birthProfile
GET /v1/model/telemetry modelTelemetry
GET /v1/budgets budgets
PUT /v1/budgets/{scope_type}/{scope_id} upsertBudget
POST /v1/budgets/{scope_type}/{scope_id}/reset resetBudget
GET /v1/audit/search auditSearch
GET /v1/audit/verify auditVerify
POST /v1/audit/export auditExport
""",
)
_surface(
    "apps/worker/src/components/BackupStatusCard.tsx",
    """
GET /v1/backup/status backupStatus
""",
)
_surface(
    "apps/worker/src/components/ParityViews.tsx",
    """
GET /v1/runs runs
POST /v1/runs/{run_id}/cancel cancelRun
GET /v1/runs/{run_id}/topology runTopology
GET /v1/audit/tree/{run_id} auditTree
GET /v1/work work
POST /v1/work createWork
GET /v1/work/{item_id} workDetail
PATCH /v1/work/{item_id}/assignment assignWork
PATCH /v1/work/{item_id}/status transitionWork
PATCH /v1/work/{item_id}/parent reparentWork
GET /v1/agent-capabilities agentCapabilities
POST /v1/agent-capabilities/{name}/retire retireAgentCapability
POST /v1/agent-capabilities/{name}/restore restoreAgentCapability
GET /v1/memory/facts memoryFacts
GET /v1/memory/facts/{fact_id} memoryFact
POST /v1/memory/recall memoryRecall
POST /v1/memory/remember memoryRemember
POST /v1/memory/improve memoryImprove
POST /v1/memory/forget memoryForget
POST /v1/memory/ingest memoryIngest
GET /v1/memory/ingestions memoryIngestions
""",
)
_surface(
    "apps/worker/src/components/knowledge/KnowledgeView.tsx",
    """
GET /v1/knowledge/assets knowledgeAssets
GET /v1/knowledge/assets/{asset_id} knowledgeAsset
DELETE /v1/knowledge/assets/{asset_id} eraseKnowledgeAsset
GET /v1/knowledge/assets/{asset_id}/original knowledgeOriginal
GET /v1/knowledge/providers knowledgeProviders
POST /v1/knowledge/providers/{provider_id} setKnowledgeProvider
POST /v1/knowledge/search knowledgeSearch
POST /v1/knowledge/uploads uploadKnowledge
PUT /v1/knowledge/uploads/{upload_id} uploadKnowledge
POST /v1/knowledge/uploads/{upload_id}/commit uploadKnowledge
""",
)
_surface(
    "apps/worker/src/components/PermanentFleetTopology.tsx",
    """
GET /v1/permanent-fleet permanentFleet
PUT /v1/permanent-fleet applyPermanentFleet
""",
)
_surface(
    "apps/worker/src/components/build/CapabilityRunner.tsx",
    """
POST /v1/invoke invoke
GET /v1/invoke/approvals/{request_id} invokeApprovalState
""",
)
_surface(
    "apps/worker/src/components/build/SpawnRulesBuild.tsx",
    """
GET /v1/spawn-rules spawnRules
POST /v1/spawn-rules/simulate simulateSpawnRules
""",
)
_surface(
    "apps/worker/src/components/AutomationView.tsx",
    """
GET /v1/capabilities capabilities
GET /v1/workflows workflows
POST /v1/workflows upsertWorkflow
GET /v1/workflows/{wf_id} workflow
POST /v1/workflows/{wf_id}/schedule scheduleWorkflow
GET /v1/workflows/{wf_id}/schedule/occurrences workflowScheduleOccurrences
POST /v1/workflows/{wf_id}/schedule/occurrences/{scheduled_for}/retry retryWorkflowScheduleOccurrence
POST /v1/workflows/{wf_id}/unschedule unscheduleWorkflow
POST /v1/workflows/{wf_id}/archive archiveWorkflow
POST /v1/workflows/{wf_id}/restore restoreWorkflow
POST /v1/workflows/{wf_id}/trigger triggerWorkflow
POST /v1/workflows/{wf_id}/execute executeWorkflow
GET /v1/workflows/{wf_id}/runs workflowRuns
GET /v1/workflow-stats workflowStats
GET /v1/workflows/{wf_id}/triggers workflowTriggers
POST /v1/workflows/{wf_id}/triggers createWorkflowTrigger
GET /v1/workflows/{wf_id}/trigger-finalizations workflowTriggerFinalizations
POST /v1/workflows/{wf_id}/triggers/{trigger_id}/enable enableWorkflowTrigger
POST /v1/workflows/{wf_id}/triggers/{trigger_id}/disable disableWorkflowTrigger
POST /v1/workflows/{wf_id}/triggers/{trigger_id}/rotate rotateWorkflowTriggerSecret
GET /v1/workflows/{wf_id}/triggers/{trigger_id}/deliveries workflowTriggerDeliveries
""",
)
_surface(
    "apps/worker/src/components/build/SkillsBuild.tsx",
    """
GET /v1/skills skills
POST /v1/skills upsertSkill
GET /v1/skills/{skill_id} skill
POST /v1/skills/{skill_id}/archive archiveSkill
POST /v1/skills/{skill_id}/restore restoreSkill
POST /v1/skills/{skill_id}/test-spawn testSpawn
GET /v1/skills/{skill_id:path} skill
POST /v1/skills/{skill_id:path}/archive archiveSkill
POST /v1/skills/{skill_id:path}/restore restoreSkill
POST /v1/skills/{skill_id:path}/test-spawn testSpawn
""",
)
_surface(
    "apps/worker/src/components/build/RegistryBuild.tsx",
    """
GET /v1/nouns nouns
POST /v1/nouns upsertNoun
GET /v1/nouns/{noun_id} noun
POST /v1/nouns/{noun_id}/archive archiveNoun
POST /v1/nouns/{noun_id}/restore restoreNoun
GET /v1/verbs verbs
POST /v1/verbs upsertVerb
GET /v1/verbs/{verb_id} verb
POST /v1/verbs/{verb_id}/archive archiveVerb
POST /v1/verbs/{verb_id}/restore restoreVerb
POST /v1/verbs/{verb_id}/binding setBinding
""",
)
_surface(
    "apps/worker/src/components/build/AdaptersBuild.tsx",
    """
GET /v1/adapters adapters
POST /v1/adapters/generate generateAdapter
GET /v1/adapters/{adapter_id}/source adapterSource
POST /v1/adapters/{adapter_id}/activate activateAdapter
POST /v1/adapters/{adapter_id}/deactivate deactivateAdapter
DELETE /v1/adapters/{adapter_id} deleteAdapter
POST /v1/mcp/servers registerMcpServer
""",
)
_surface(
    "apps/worker/src/components/build/McpServersBuild.tsx",
    """
GET /v1/mcp/servers mcpServers
GET /v1/mcp/servers/{server_id} mcpServer
PUT /v1/mcp/servers/{server_id} updateMcpServer
DELETE /v1/mcp/servers/{server_id} deleteMcpServer
POST /v1/mcp/servers/{server_id}/probe probeMcpServer
POST /v1/mcp/servers/{server_id}/activate activateMcpServer
POST /v1/mcp/servers/{server_id}/deactivate deactivateMcpServer
POST /v1/mcp/servers/{server_id}/retire retireMcpServer
POST /v1/mcp/servers/{server_id}/restore restoreMcpServer
""",
)
_surface(
    "apps/worker/src/components/build/RecentlyChanged.tsx",
    """
GET /v1/capabilities/changelog capabilityChangelog
""",
)
_surface(
    "apps/worker/src/components/build/ModelEndpointsBuild.tsx",
    """
GET /v1/model-endpoints modelEndpoints
GET /v1/model-policy modelPolicy
GET /v1/model-endpoints/{endpoint_id} modelEndpoint
POST /v1/model-endpoints/{endpoint_id}/retire retireModelEndpoint
POST /v1/model-endpoints/{endpoint_id}/restore restoreModelEndpoint
""",
)
_surface(
    "apps/worker/src/components/ChannelsView.tsx",
    """
GET /v1/channels channels
POST /v1/channels connectChannel
POST /v1/channels/gateway/session channelGatewaySession
PATCH /v1/channels/{channel_id} configureChannel
DELETE /v1/channels/{channel_id} disconnectChannel
GET /v1/channels/{channel_id}/bindings channelBindings
POST /v1/channels/{channel_id}/bindings bindChannel
DELETE /v1/channels/{channel_id}/bindings/{binding_id} deleteChannelBinding
GET /v1/channels/{channel_id}/pair-finalizations channelPairFinalizations
GET /v1/channels/{channel_id}/deliveries channelDeliveries
POST /v1/channels/{channel_id}/deliveries/{message_id}/retry retryChannelDelivery
POST /v1/channels/{channel_id}/pair pairChannel
""",
)
_surface(
    "apps/worker/src/components/EvaluationsView.tsx",
    """
GET /v1/eval/cases evalCases
POST /v1/eval/cases createEvalCase
POST /v1/eval/cases/{case_id}/archive archiveEvalCase
POST /v1/eval/cases/{case_id}/restore restoreEvalCase
POST /v1/eval/run runEval
GET /v1/eval/runs evalRuns
""",
)
_surface(
    "apps/worker/src/components/InboxHitl.tsx",
    """
GET /v1/hitl hitl
GET /v1/hitl/policy hitlPolicy
POST /v1/hitl/{request_id}/respond respondHitl
POST /v1/hitl/{question_id}/answer answerQuestion
""",
)
_surface(
    "apps/worker/src/components/IntegrationsView.tsx",
    """
GET /v1/addons addons
GET /v1/integrations/catalogue integrationCatalogue
GET /v1/integrations/connections integrationConnections
GET /v1/integrations/connections/{connection_id}/health integrationConnectionHealth
POST /v1/integrations/{integration_id}/oauth/start startIntegrationOAuth
POST /v1/integrations/{integration_id}/secrets submitIntegrationSecret
DELETE /v1/integrations/connections/{connection_id} disconnectIntegration
""",
)
_surface(
    "apps/worker/src/components/DeviceSettings.tsx",
    """
GET /v1/devices devices
POST /v1/devices/enrollment/start startDeviceEnrollment
DELETE /v1/devices/{device_id} revokeDevice
POST /v1/devices/{device_id}/roots createDeviceRoot
DELETE /v1/devices/{device_id}/roots/{root_id} revokeDeviceRoot
""",
)
_surface(
    "apps/worker/src/components/LocalDeviceActions.tsx",
    """
GET /v1/devices/{device_id}/leases deviceLeases
""",
)
_surface(
    "apps/worker/src/components/VoiceCall.tsx",
    """
GET /v1/calls calls
POST /v1/calls createCall
GET /v1/calls/current currentCall
POST /v1/calls/{call_id}/end endCall
GET /v1/calls/{call_id}/events callEvents
POST /v1/calls/{call_id}/reopen reopenCall
GET /v1/calls/{call_id}/usage callUsage
""",
)


INDIRECT_WORKER_ROUTES: dict[Route, IndirectWorkerSurface] = {
    ("GET", "/v1/artifacts/{artifact_id}"): IndirectWorkerSurface(
        sdk_method="artifact",
        replacement_method="artifacts",
        source="apps/worker/src/components/ChatView.tsx",
        rationale="the paged list returns the complete immutable Artifact projection",
    ),
    ("GET", "/v1/calls/{call_id}"): IndirectWorkerSurface(
        sdk_method="getCall",
        replacement_method="calls",
        source="apps/worker/src/components/VoiceCall.tsx",
        rationale="recent/current call projections already contain the complete call record",
    ),
    ("POST", "/v1/calls/{call_id}/media-token"): IndirectWorkerSurface(
        sdk_method="refreshCallMedia",
        replacement_method="reopenCall",
        source="apps/worker/src/components/VoiceCall.tsx",
        rationale="Worker recovery reopens the same call and receives a fresh media session",
    ),
}


NON_UI_ROUTES: dict[Route, str] = {}


def _non_ui(classification: str, declarations: str) -> None:
    for declaration in declarations.strip().splitlines():
        method, path = declaration.split()
        route = (method, path)
        if route in NON_UI_ROUTES:
            raise ValueError(f"duplicate non-UI route declaration: {route}")
        NON_UI_ROUTES[route] = classification


_non_ui("service-probe", "GET /healthz")
_non_ui(
    "operator-only",
    """
POST /v1/admin/config/export
GET /v1/admin/config/{section}
PUT /v1/admin/config/{section}
GET /v1/admin/config/{section}/history
POST /v1/admin/config/{section}/rollback
GET /v1/admin/credentials
GET /v1/runs/{run_id}/events
""",
)
_non_ui(
    "external-ingress",
    """
POST /v1/automation-hooks/{tenant_id}/{trigger_id}
POST /v1/mcp
""",
)
_non_ui(
    "service-native",
    """
POST /v1/calls/gateway/claim
POST /v1/calls/gateway/{call_id}/events
GET /v1/calls/gateway/{call_id}/hitl/{request_id}
POST /v1/calls/gateway/{call_id}/state
GET /v1/channels/gateway/reconcile
POST /v1/channels/gateway/heartbeat
POST /v1/channels/gateway/outbox/claim
POST /v1/channels/gateway/outbox/{message_id}/ack
POST /v1/channels/gateway/outbox/{message_id}/fail
POST /v1/channels/{channel_id}/inbound
POST /v1/device-agent/enrollment/complete
GET /v1/device-agent/{device_id}/leases
POST /v1/device-agent/{device_id}/leases/{lease_id}/claim
POST /v1/device-agent/{device_id}/leases/{lease_id}/receipt
POST /v1/device-agent/{device_id}/session/rotate
GET /v1/hands/commands
POST /v1/hands/commands/{cmd_id}/receipt
""",
)
_non_ui("internal-composition", "POST /v1/knowledge/context")
_non_ui("legacy-superseded", "POST /v1/memory/query")
_non_ui("advanced-compatibility", "POST /v1/spawn")


SDK_ONLY_METHODS: dict[str, tuple[str, str]] = {
    "artifact": (
        "superseded-read",
        "Artifact list rows contain the complete detail projection.",
    ),
    "artifactDownloadUrl": (
        "internal-helper",
        "downloadArtifact uses this URL helper and Chat calls downloadArtifact.",
    ),
    "getCall": (
        "superseded-read",
        "calls/currentCall already return the complete call projection.",
    ),
    "refreshCallMedia": (
        "compatibility-helper",
        "Worker uses reopenCall for recovery and fresh media credentials.",
    ),
    "spawn": (
        "advanced-compatibility",
        "Ordinary delegation uses chat, personal-agent and bounded test-spawn flows.",
    ),
}


EXPECTED_ROUTE_COUNT = 257
