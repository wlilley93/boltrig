"""Worker fixed controls share one exact, non-secret caller resume lane."""

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
COMPONENTS = ROOT / "apps" / "worker" / "src" / "components"
TARGETS = (
    "AccountAutomationSections.tsx",
    "AgentProfileEditor.tsx",
    "OrganisationDirectorySections.tsx",
    "OrganisationWorkspaceSections.tsx",
    "OperationsView.tsx",
    "ParityViews.tsx",
    "PermanentFleetTopology.tsx",
    "build/ModelEndpointsBuild.tsx",
    "build/RegistryBuild.tsx",
    "build/SkillsBuild.tsx",
)
GENERIC_INVOKE_TARGETS = {
    "AgentProfileEditor.tsx",
    "build/ModelEndpointsBuild.tsx",
}
COMPLETE_CALLER_LANE_SURFACES = (
    "AutomationView.tsx",
    "ChannelsView.tsx",
    "EvaluationsView.tsx",
)


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-32")
def test_fixed_control_families_use_the_shared_exact_finalizer() -> None:
    shared = (COMPONENTS / "ExactApprovalFinalizer.tsx").read_text(
        encoding="utf-8"
    )
    assert "client.invokeApprovalState" in shared
    assert "cloneRouteInput" in shared
    assert "approvalId" in shared
    assert "replay(pending.input, pending.approvalId)" in shared
    for state in (
        "waiting",
        "rejected",
        "expired",
        "consumed",
        "unavailable",
        "invalidated",
    ):
        assert f'"{state}"' in shared

    for filename in TARGETS:
        source = (COMPONENTS / filename).read_text(encoding="utf-8")
        assert "useExactApprovalFinalizer" in source, filename
        assert "<ExactApprovalFinalizer" in source, filename
        assert ".begin(" in source, filename
        assert ".invalidate()" in source, filename
        if filename in GENERIC_INVOKE_TARGETS:
            assert source.count("approval_id: approvalId") == 1, filename
        else:
            assert "approval_id" not in source, filename
        assert 'name="approval_id"' not in source, filename
        assert "setApprovalId" not in source, filename

    for filename in COMPLETE_CALLER_LANE_SURFACES:
        source = (COMPONENTS / filename).read_text(encoding="utf-8")
        assert "useExactApprovalFinalizer" in source, filename
        assert "<ExactApprovalFinalizer" in source, filename
        assert "exactApproval.begin(" in source, filename
        assert (
            "exactApprovalInvalidator.current = exactApproval.invalidate"
            in source
        ), filename
        assert 'name="approval_id"' not in source, filename
        assert "setApprovalId" not in source, filename

    sdk = (ROOT / "sdks" / "web" / "src" / "client.ts").read_text(
        encoding="utf-8"
    )
    for method in (
        "putMeNotification",
        "patchUser",
        "createInvitation",
        "revokeInvitation",
        "updateCurrentOrg",
        "createWorkspace",
        "updateWorkspace",
        "addWorkspaceMember",
        "removeWorkspaceMember",
        "upsertBudget",
        "resetBudget",
        "applyPermanentFleet",
        "retireModelEndpoint",
        "restoreModelEndpoint",
        "upsertSkill",
        "archiveSkill",
        "restoreSkill",
        "upsertNoun",
        "archiveNoun",
        "restoreNoun",
        "upsertVerb",
        "archiveVerb",
        "restoreVerb",
        "setBinding",
        "upsertWorkflow",
        "scheduleWorkflow",
        "unscheduleWorkflow",
        "archiveWorkflow",
        "restoreWorkflow",
        "triggerWorkflow",
        "executeWorkflow",
        "createEvalCase",
        "archiveEvalCase",
        "restoreEvalCase",
        "connectChannel",
        "configureChannel",
        "disconnectChannel",
        "retryChannelDelivery",
        "pairChannel",
        "bindChannel",
        "deleteChannelBinding",
    ):
        start = sdk.index(f"  {method}(")
        snippet = sdk[start : start + 900]
        assert "approvalId?: string" in snippet, method
        assert "governedJson(" in snippet, method


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-32")
def test_pairing_code_uses_a_purpose_specific_one_time_finalizer() -> None:
    source = (COMPONENTS / "ChannelsView.tsx").read_text(encoding="utf-8")
    discovery = (
        ROOT / "boltrig" / "kernel" / "channel_pair_finalization.py"
    ).read_text(encoding="utf-8")
    pending_start = source.index("interface PendingPairingFinalization")
    pending_end = source.index("type ExactChannelMutation", pending_start)
    pending_contract = source[pending_start:pending_end]

    assert "channelPairFinalizations" in source
    assert "finalizePairing" in source
    assert "approvalId: string" in pending_contract
    assert "body: PairChannelRequest" in pending_contract
    assert "code:" not in pending_contract
    assert "list_hitl_requests_for_requester" in discovery
    assert '"code"' not in discovery
    assert "never a generated code" in discovery


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-32")
def test_secret_bearing_ai_key_flow_is_not_a_generic_retained_mutation() -> None:
    source = (COMPONENTS / "AiKeyManagement.tsx").read_text(encoding="utf-8")
    # Non-secret delete may use the generic exact lane. Set must instead clear
    # its uncontrolled input and continue only by opaque proposal id.
    assert "deleteFinalizer = useExactApprovalFinalizer" in source
    assert "ref={apiKeyInput}" in source
    assert 'input.value = "";' in source
    assert "client.finalizeAiKeyProposal(proposal.id)" in source
    assert "const [apiKey" not in source
