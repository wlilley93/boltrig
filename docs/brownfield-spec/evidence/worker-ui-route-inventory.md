# Evidence: Worker UI module, route and SDK-call inventory

Referent commit `19bcae7fa81663fe8998377c86451ba08fb16e48`, generated 2026-08-24 from
the pinned tree at `/var/tmp/claude/claude-1011/-home-jellytot/f7f5f72e-a248-4744-a573-952de9fdf71f/scratchpad/bt-spec`.
Companion to `docs/brownfield-spec/specs/SPEC-15-worker-ui.md`, section 4.2.

## How every table here was produced

Mechanically, not by reading. Each module under `apps/worker/src` was parsed for
the regex `\bclient\.([A-Za-z_][A-Za-z0-9_]*)\s*\(` (the single shared SDK
instance from `apps/worker/src/client.ts`), and for relative import specifiers
`from "./x"` and `import("./x")` resolved against `.ts`, `.tsx` and `index.*`.
Line counts are newline counts. Three consequences of that method, stated so a
reader does not over-read the tables:

1. A call reached through an alias (`const api = client; api.runs()`) is NOT
   counted. No such alias was found (bounded: `rg -n "= client;|= client," apps/worker/src`,
   2026-08-24, pinned tree, no hits).
2. A dynamic `import()` with a computed specifier is not resolved. None exists
   (bounded: `rg -no "import\([^)]*\)" apps/worker/src`, 2026-08-24, pinned tree:
   every hit is a literal, and the only non-relative one is
   `import("@wlilley93/boltrig-web-sdk")` in `src/components/characters.ts`).
3. "No importer" means no importer INSIDE `apps/worker/src`. A module can still
   be an entry point (`src/main.tsx`, `src/familiarIsland/main.ts`) or be reached
   only from `apps/worker/tests`. Table D separates those cases.

## Table A: the sixteen hash routes and what mounts them

Source: the two switch statements in
`apps/worker/src/components/shell/AppRouteSurface.tsx` lines 68 to 106, and the
lazy binding table at lines 9 to 32.

| hash | mounted component | module | chunk | note |
|---|---|---|---|---|
| `#/home` | HomeView or MobileToday under 640px | `src/components/OperationsView.tsx, src/components/MobileToday.tsx` | lazy (HomeView), eager (MobileToday) | MobileToday is a static import at line 6, so it is in the entry chunk |
| `#/chat` | ChatView, or LocalChatView with a Tauri runtime | `src/components/ChatView.tsx, src/components/LocalChatView.tsx` | lazy | the only runtime-switched route |
| `#/runs` | RunsView | `src/components/ParityViews.tsx` | lazy | shares one chunk with Work, Agents, Knowledge, Memory |
| `#/work` | WorkView | `src/components/ParityViews.tsx` | lazy |  |
| `#/agents` | AgentsView | `src/components/ParityViews.tsx` | lazy |  |
| `#/account` | SettingsView section=you | `src/components/Views.tsx` | lazy | does NOT mount src/components/AccountView.tsx |
| `#/build` | BuildView | `src/components/BuildView.tsx` | lazy | seven internal tabs |
| `#/browser` | BrowserWorkspace | `src/components/browser/BrowserWorkspace.tsx` | lazy |  |
| `#/channels` | ChannelsView | `src/components/ChannelsView.tsx` | lazy |  |
| `#/evaluations` | EvaluationsView | `src/components/EvaluationsView.tsx` | lazy |  |
| `#/automations` | RoutinesView | `src/components/RoutinesView.tsx` | lazy | does NOT mount src/components/AutomationView.tsx |
| `#/knowledge` | KnowledgeView | `src/components/knowledge/KnowledgeView.tsx via ParityViews` | lazy |  |
| `#/memory` | MemoryView | `src/components/ParityViews.tsx` | lazy |  |
| `#/integrations` | IntegrationsSurface | `src/components/integrations/IntegrationsSurface.tsx` | lazy | three internal tabs |
| `#/organisation` | OrganisationView | `src/components/OrganisationView.tsx` | lazy |  |
| `#/settings` | SettingsView, MobileSettings under 640px, SettingsSearchResults while a query is set | `src/components/Views.tsx, src/components/MobileSettings.tsx, src/components/settings/SearchResults.tsx` | lazy | three components behind one hash |

## Table B: every module under `apps/worker/src`

335 modules, 69528 lines. `SDK methods` lists every distinct `client.<method>(`
call site in that file; an empty cell means the module makes no backend call of
its own.

| module | lines | SDK methods called |
|---|---:|---|
| `src/App.tsx` | 30 | - |
| `src/aiKeyIntake.ts` | 21 | `setAiKey` |
| `src/apiOrigin.ts` | 45 | - |
| `src/character.ts` | 161 | - |
| `src/characterPlugins.ts` | 20 | - |
| `src/characterVoice.ts` | 156 | - |
| `src/client.ts` | 48 | - |
| `src/clipboard.ts` | 17 | - |
| `src/components/AccountAutomationSections.tsx` | 388 | `configurePersonalAgent`, `deletePersonalAgent`, `invokePersonalAgent`, `meAgent`, `meNotifications`, `putMeNotification`, `testMeNotification` |
| `src/components/AccountProfileSections.tsx` | 265 | `meActivity`, `meExport`, `privacyPolicy`, `putMeSettings`, `updateMeProfile` |
| `src/components/AccountSecuritySections.tsx` | 371 | `changePassword`, `meSessions`, `meTokens`, `mintToken`, `revokeSession`, `revokeToken`, `twoFactorDisable`, `twoFactorEnrollBegin`, `twoFactorVerifyEnroll` |
| `src/components/AccountView.tsx` | 98 | `meSettings` |
| `src/components/AgentProfileEditor.tsx` | 244 | `agentCapabilities`, `invoke`, `modelEndpoints` |
| `src/components/AiKeyManagement.tsx` | 315 | `aiKeyProposal`, `aiKeyProposals`, `aiKeys`, `deleteAiKey`, `finalizeAiKeyProposal`, `invalidateAiKeyProposal`, `setAiKey` |
| `src/components/ApprovalPostureControl.tsx` | 353 | `approvalPosture`, `putApprovalPosture` |
| `src/components/AuthGate.tsx` | 171 | `meSettings`, `refreshSession`, `sessionCsrf` |
| `src/components/AutomationView.tsx` | 2870 | `archiveWorkflow`, `capabilities`, `channels`, `createWorkflowTrigger`, `disableWorkflowTrigger`, `enableWorkflowTrigger`, `executeWorkflow`, `invokeApprovalState`, `restoreWorkflow`, `retryWorkflowScheduleOccurrence`, `rotateWorkflowTriggerSecret`, `scheduleWorkflow`, `triggerWorkflow`, `unscheduleWorkflow`, `upsertWorkflow`, `workflow`, `workflowRuns`, `workflowScheduleOccurrences`, `workflowStats`, `workflowTriggerDeliveries`, `workflowTriggerFinalizations`, `workflowTriggers`, `workflows` |
| `src/components/BackupStatusCard.tsx` | 65 | `backupStatus` |
| `src/components/BrandMark.tsx` | 90 | - |
| `src/components/BrandWordmark.tsx` | 20 | - |
| `src/components/BuildView.tsx` | 287 | - |
| `src/components/CameraDiscoverySettings.tsx` | 118 | - |
| `src/components/ChannelProvenanceFacts.tsx` | 52 | - |
| `src/components/ChannelsView.tsx` | 2141 | `bindChannel`, `channelBindings`, `channelDeliveries`, `channelGatewaySession`, `channelPairFinalizations`, `channels`, `configureChannel`, `connectChannel`, `deleteChannelBinding`, `disconnectChannel`, `invoke`, `invokeApprovalState`, `pairChannel`, `retryChannelDelivery` |
| `src/components/ChatView.tsx` | 1324 | `artifacts`, `cancelRun`, `conversation`, `conversations`, `downloadArtifact`, `followConversation`, `respondHitl`, `streamChat` |
| `src/components/CommandPalette.tsx` | 564 | `federatedSearch` |
| `src/components/ConnectionInstructions.tsx` | 67 | `meConnections` |
| `src/components/ConversationControls.tsx` | 167 | `deleteMyConversation`, `regenerateMessage`, `renameConversation`, `restoreMyConversation` |
| `src/components/DesktopUpdater.tsx` | 214 | - |
| `src/components/DeviceSettings.tsx` | 517 | `createDeviceRoot`, `devices`, `revokeDevice`, `revokeDeviceRoot` |
| `src/components/EvaluationsView.tsx` | 578 | `archiveEvalCase`, `createEvalCase`, `evalCases`, `evalRuns`, `restoreEvalCase`, `runEval` |
| `src/components/ExactApprovalFinalizer.tsx` | 294 | `invokeApprovalState` |
| `src/components/GovernedCreateModal.tsx` | 142 | - |
| `src/components/InboxHitl.tsx` | 354 | `answerQuestion`, `hitl`, `hitlPolicy`, `respondHitl` |
| `src/components/IntegrationsView.tsx` | 1526 | `addons`, `disconnectIntegration`, `integrationCatalogue`, `integrationConnectionHealth`, `integrationConnections`, `mcpServers`, `startIntegrationOAuth`, `submitIntegrationSecret` |
| `src/components/LiveQuestionCard.tsx` | 83 | `answerQuestion` |
| `src/components/LocalChatView.tsx` | 238 | - |
| `src/components/LocalDeviceActions.tsx` | 583 | `deviceLeases`, `invoke`, `invokeApprovalState` |
| `src/components/MemorySurface.tsx` | 290 | `memoryCandidateReview`, `memoryCandidates`, `memoryTimeline`, `respondHitl` |
| `src/components/MobileChat.tsx` | 430 | - |
| `src/components/MobileSettings.tsx` | 142 | - |
| `src/components/MobileToday.tsx` | 83 | `conversations`, `hitl`, `respondHitl` |
| `src/components/MobileTodaySections.tsx` | 144 | - |
| `src/components/OperationsView.tsx` | 1282 | `auditExport`, `auditSearch`, `auditVerify`, `birthProfile`, `budgets`, `consoleOverview`, `modelTelemetry`, `platformStatus`, `readiness`, `resetBudget`, `upsertBudget` |
| `src/components/OrganisationDirectorySections.tsx` | 531 | `adminInvitations`, `adminUsers`, `createInvitation`, `orgMembers`, `patchUser`, `revokeInvitation` |
| `src/components/OrganisationView.tsx` | 100 | `currentOrg`, `meSettings` |
| `src/components/OrganisationWorkspaceSections.tsx` | 762 | `addWorkspaceMember`, `createWorkspace`, `removeWorkspaceMember`, `updateCurrentOrg`, `updateWorkspace`, `workspaceMembers`, `workspaces` |
| `src/components/ParityViews.tsx` | 1577 | `agentCapabilities`, `assignWork`, `auditTree`, `cancelRun`, `createWork`, `hitl`, `memoryFact`, `memoryFacts`, `memoryForget`, `memoryImprove`, `memoryIngest`, `memoryIngestions`, `memoryRecall`, `memoryRemember`, `reparentWork`, `restoreAgentCapability`, `retireAgentCapability`, `runTopology`, `runs`, `transitionWork`, `work`, `workDetail` |
| `src/components/PermanentFleetTopology.tsx` | 1139 | `applyPermanentFleet`, `modelEndpoints`, `permanentFleet` |
| `src/components/RoutineThumb.tsx` | 171 | - |
| `src/components/RoutinesView.tsx` | 60 | - |
| `src/components/SettingsSurface.tsx` | 161 | `budgets` |
| `src/components/Shell.tsx` | 507 | `logout` |
| `src/components/StageBody.tsx` | 192 | `budgets`, `sensingCapability` |
| `src/components/Views.tsx` | 32 | - |
| `src/components/VoiceCall.tsx` | 1525 | `callEvents`, `callUsage`, `calls`, `capabilities`, `createCall`, `currentCall`, `endCall`, `reopenCall` |
| `src/components/WorkerErrorBoundary.tsx` | 127 | - |
| `src/components/WorkerGlobalContext.tsx` | 112 | `consoleOverview`, `currentOrg`, `meSettings`, `workspaces` |
| `src/components/account/ActiveContext.tsx` | 59 | - |
| `src/components/account/useActiveContext.ts` | 100 | `consoleOverview`, `currentOrg`, `myOrganisations`, `switchActiveContext`, `switchActiveOrg`, `workspaces` |
| `src/components/agent/AgentModelRouting.tsx` | 92 | - |
| `src/components/auth/AcceptInviteScreen.tsx` | 70 | `acceptInvite` |
| `src/components/auth/AccountRequirementScreens.tsx` | 178 | `changePassword`, `twoFactorChallenge`, `twoFactorEnrollBegin`, `twoFactorVerifyEnroll` |
| `src/components/auth/AuthShell.tsx` | 66 | - |
| `src/components/auth/DesktopAccountBridge.tsx` | 49 | - |
| `src/components/auth/LoginScreen.tsx` | 65 | `login` |
| `src/components/auth/RecoveryScreens.tsx` | 134 | `confirmPasswordReset`, `requestPasswordReset` |
| `src/components/auth/routing.ts` | 21 | - |
| `src/components/auth/types.ts` | 8 | - |
| `src/components/auth/useDesktopAccountBridge.ts` | 93 | `devices` |
| `src/components/browser/BrowserWorkspace.tsx` | 131 | - |
| `src/components/browser/BrowserWorkspaceModel.ts` | 100 | - |
| `src/components/browser/useBrowserWorkspace.tsx` | 205 | `invoke` |
| `src/components/build/ActionApprovalPresentation.tsx` | 93 | `approvalPosture`, `hitlPolicy` |
| `src/components/build/ActionsTable.tsx` | 120 | `verbs` |
| `src/components/build/AdaptersBuild.tsx` | 397 | `activateAdapter`, `adapterSource`, `adapters`, `deactivateAdapter`, `deleteAdapter`, `generateAdapter`, `registerMcpServer` |
| `src/components/build/AgentTabsStrip.tsx` | 39 | - |
| `src/components/build/CapabilityRunner.tsx` | 657 | `capabilities`, `invoke`, `invokeApprovalState` |
| `src/components/build/McpServersBuild.tsx` | 743 | `activateMcpServer`, `deactivateMcpServer`, `deleteMcpServer`, `mcpServer`, `mcpServers`, `probeMcpServer`, `restoreMcpServer`, `retireMcpServer`, `updateMcpServer` |
| `src/components/build/ModelEndpointsBuild.tsx` | 418 | `invoke`, `modelEndpoint`, `modelEndpoints`, `modelPolicy`, `restoreModelEndpoint`, `retireModelEndpoint` |
| `src/components/build/RecentlyChanged.tsx` | 122 | `capabilityChangelog` |
| `src/components/build/RegistryBuild.tsx` | 610 | `archiveNoun`, `archiveVerb`, `noun`, `nouns`, `restoreNoun`, `restoreVerb`, `setBinding`, `upsertNoun`, `upsertVerb`, `verb`, `verbs` |
| `src/components/build/SkillsBuild.tsx` | 343 | `archiveSkill`, `restoreSkill`, `skill`, `skills`, `testSpawn`, `upsertSkill` |
| `src/components/build/SkillsTable.tsx` | 148 | `agentCapabilities`, `skill`, `skills` |
| `src/components/build/SpawnRulesBuild.tsx` | 158 | `simulateSpawnRules`, `spawnRules` |
| `src/components/build/result.ts` | 29 | - |
| `src/components/canvas/bodyClock.ts` | 113 | - |
| `src/components/canvas/bodyEmotion.ts` | 212 | - |
| `src/components/canvas/bodyModes.ts` | 155 | - |
| `src/components/canvas/bodyPresets.ts` | 33 | - |
| `src/components/canvas/bodyRamp.ts` | 59 | - |
| `src/components/canvas/bodyTuning.ts` | 22 | - |
| `src/components/canvas/canvasBob.ts` | 15 | - |
| `src/components/canvas/familiarPresets.ts` | 183 | - |
| `src/components/canvas/familiarTuning.ts` | 188 | - |
| `src/components/canvas/fitCanvas.ts` | 17 | - |
| `src/components/canvas/glResources.ts` | 165 | - |
| `src/components/canvas/glslCommon.ts` | 190 | - |
| `src/components/canvas/glslField.ts` | 277 | - |
| `src/components/canvas/jarvisPresets.ts` | 325 | - |
| `src/components/canvas/jarvisTuning.ts` | 337 | - |
| `src/components/canvas/latticeLayer.ts` | 336 | - |
| `src/components/canvas/shadersIris.ts` | 137 | - |
| `src/components/canvas/shadersPost.ts` | 229 | - |
| `src/components/canvas/shadersSim.ts` | 111 | - |
| `src/components/canvas/speechReach.ts` | 47 | - |
| `src/components/canvas/ultronPresets.ts` | 192 | - |
| `src/components/canvas/ultronTuning.ts` | 240 | - |
| `src/components/characterBundle.ts` | 208 | - |
| `src/components/characters.ts` | 365 | - |
| `src/components/chat/AgentChip.tsx` | 33 | - |
| `src/components/chat/ChatMessages.tsx` | 206 | - |
| `src/components/chat/CompactionLine.tsx` | 45 | - |
| `src/components/chat/Composer.tsx` | 355 | - |
| `src/components/chat/ComposerAddMenu.tsx` | 220 | - |
| `src/components/chat/ComposerAttachments.tsx` | 279 | - |
| `src/components/chat/InlineApproval.tsx` | 208 | `hitl`, `invokeApprovalState`, `respondHitl` |
| `src/components/chat/MobileQueuedMessages.tsx` | 61 | - |
| `src/components/chat/ModelChip.tsx` | 167 | - |
| `src/components/chat/ModelRuntimePopover.tsx` | 168 | - |
| `src/components/chat/OrderedWorkTranscript.tsx` | 161 | - |
| `src/components/chat/PersistedDecision.tsx` | 106 | `invokeApprovalState` |
| `src/components/chat/QueuedMessages.tsx` | 288 | - |
| `src/components/chat/RoutineRunBanner.tsx` | 48 | - |
| `src/components/chat/RunSectionFormat.ts` | 67 | - |
| `src/components/chat/RunSectionView.test.tsx` | 196 | - |
| `src/components/chat/RunSectionView.tsx` | 312 | `auditTree`, `runTopology` |
| `src/components/chat/RunUndoPanel.tsx` | 143 | `revertRun`, `runEffects` |
| `src/components/chat/SubagentChips.tsx` | 136 | - |
| `src/components/chat/SubagentTabs.test.tsx` | 138 | - |
| `src/components/chat/SubagentTabs.tsx` | 284 | `auditTree` |
| `src/components/chat/TaskInspector.test.tsx` | 360 | - |
| `src/components/chat/TaskInspector.tsx` | 803 | - |
| `src/components/chat/TaskInspectorModel.ts` | 289 | - |
| `src/components/chat/ThemeToggle.tsx` | 31 | - |
| `src/components/chat/ToolReceiptDetails.tsx` | 233 | `runEvents` |
| `src/components/chat/TranscriptBody.tsx` | 55 | - |
| `src/components/chat/TranscriptNavigation.tsx` | 79 | - |
| `src/components/chat/VoiceBanner.tsx` | 64 | - |
| `src/components/chat/Welcome.tsx` | 12 | - |
| `src/components/chat/WorkDisclosure.tsx` | 137 | - |
| `src/components/chat/attachmentPresentation.ts` | 64 | - |
| `src/components/chat/chatErrors.ts` | 13 | - |
| `src/components/chat/colossusReply.ts` | 85 | - |
| `src/components/chat/display/CommunicationDraftCard.tsx` | 186 | - |
| `src/components/chat/display/DecisionDisplayCards.tsx` | 189 | - |
| `src/components/chat/display/DisplayFields.tsx` | 83 | - |
| `src/components/chat/display/DisplayObjectBlocks.tsx` | 164 | - |
| `src/components/chat/display/DisplayObjectCard.tsx` | 100 | - |
| `src/components/chat/display/DisplayObjectList.tsx` | 39 | - |
| `src/components/chat/display/displayObjectData.ts` | 202 | - |
| `src/components/chat/modelAvailabilityCopy.ts` | 17 | - |
| `src/components/chat/modelChipOptions.ts` | 59 | - |
| `src/components/chat/pendingChatTarget.ts` | 24 | - |
| `src/components/chat/speechTakeaway.ts` | 119 | - |
| `src/components/chat/stageTurnInput.ts` | 42 | - |
| `src/components/chat/thinkingTrace.ts` | 16 | - |
| `src/components/chat/toolActivity.ts` | 55 | - |
| `src/components/chat/toolVerbPresentation.ts` | 52 | - |
| `src/components/chat/useChatAgentSelection.ts` | 139 | `namedAgents` |
| `src/components/chat/useChatModelOptions.ts` | 57 | `chatConfig`, `chatModelChoices` |
| `src/components/chat/useChatProjection.test.ts` | 65 | - |
| `src/components/chat/useChatProjection.ts` | 181 | - |
| `src/components/chat/useCompactionBoundary.ts` | 22 | - |
| `src/components/chat/useConversationQueue.ts` | 98 | `reorderConversationQueue` |
| `src/components/chat/useLocalChatController.ts` | 388 | - |
| `src/components/chat/useModelChipOptions.ts` | 28 | - |
| `src/components/chat/useReplySpeech.ts` | 337 | `capabilities`, `invoke`, `meSettings` |
| `src/components/chat/useStagePhenotype.ts` | 42 | `familiarPhenotype` |
| `src/components/chat/useTechDetails.ts` | 29 | `meSettings` |
| `src/components/chat/useTranscriptViewport.test.tsx` | 323 | - |
| `src/components/chat/useTranscriptViewport.ts` | 279 | - |
| `src/components/colossus/ColossusRenderer.ts` | 313 | - |
| `src/components/colossus/ColossusStage.tsx` | 99 | - |
| `src/components/colossus/ColossusState.ts` | 123 | - |
| `src/components/colossus/colossusPasses.ts` | 262 | - |
| `src/components/colossus/colossusTuning.ts` | 74 | - |
| `src/components/colossus/glyphAtlas.ts` | 136 | - |
| `src/components/colossus/shadersColossus.ts` | 386 | - |
| `src/components/colossus/tickerBed.ts` | 94 | - |
| `src/components/colossus/tickerText.ts` | 108 | - |
| `src/components/contentText.ts` | 15 | - |
| `src/components/deviceSettingsVisibility.ts` | 26 | - |
| `src/components/familiar/FamiliarBadge.tsx` | 157 | - |
| `src/components/familiar/FamiliarGenotype.ts` | 217 | - |
| `src/components/familiar/FamiliarStage.tsx` | 83 | - |
| `src/components/familiar/FamiliarState.ts` | 165 | - |
| `src/components/familiar/FamiliarWebGLRenderer.ts` | 398 | - |
| `src/components/familiar/familiarDrive.ts` | 261 | - |
| `src/components/familiar/familiarMood.ts` | 230 | - |
| `src/components/familiar/familiarUniforms.ts` | 126 | - |
| `src/components/familiar/useFamiliarRenderer.ts` | 81 | - |
| `src/components/integrations/CapabilityCataloguePanel.tsx` | 98 | `capabilityCatalogue` |
| `src/components/integrations/CapabilityReviewPanel.tsx` | 160 | - |
| `src/components/integrations/ConnectionSurface.tsx` | 74 | - |
| `src/components/integrations/IntegrationsSurface.tsx` | 52 | - |
| `src/components/integrations/IntegrationsTabs.tsx` | 43 | - |
| `src/components/integrations/ManualSecretSetup.tsx` | 171 | - |
| `src/components/integrations/MemberConnections.tsx` | 127 | `memberIntegrationConnections`, `revokeMemberIntegrationConnection` |
| `src/components/integrations/PluginPicker.tsx` | 198 | - |
| `src/components/integrations/RoutingRulesPanel.tsx` | 90 | `routingPolicies` |
| `src/components/integrations/capabilityTabs.ts` | 38 | - |
| `src/components/integrations/useCapabilityReviewQueue.ts` | 128 | `capabilityBindings`, `invoke` |
| `src/components/jarvis/JarvisGauge.ts` | 50 | - |
| `src/components/jarvis/JarvisGenotype.ts` | 75 | - |
| `src/components/jarvis/JarvisLabels.tsx` | 242 | - |
| `src/components/jarvis/JarvisMotion.ts` | 96 | - |
| `src/components/jarvis/JarvisRenderer.ts` | 728 | - |
| `src/components/jarvis/JarvisStage.tsx` | 111 | - |
| `src/components/jarvis/JarvisState.ts` | 149 | - |
| `src/components/jarvis/JarvisTelemetry.ts` | 89 | - |
| `src/components/jarvis/JarvisWork.ts` | 83 | - |
| `src/components/jarvis/geometry.ts` | 47 | - |
| `src/components/jarvis/jarvisInstrumentUniforms.ts` | 57 | - |
| `src/components/jarvis/jarvisLiveKnobs.ts` | 41 | - |
| `src/components/jarvis/jarvisPhenotype.ts` | 28 | - |
| `src/components/jarvis/useJarvisRenderer.ts` | 132 | - |
| `src/components/jarvis/v2/JarvisNeuralRenderer.ts` | 398 | - |
| `src/components/jarvis/v2/glslClump.ts` | 29 | - |
| `src/components/jarvis/v2/jarvisDrive.ts` | 79 | - |
| `src/components/jarvis/v2/neuralPasses.ts` | 318 | - |
| `src/components/jarvis/v2/neuralScenePasses.ts` | 204 | - |
| `src/components/jarvis/v2/shadersField.ts` | 215 | - |
| `src/components/jarvis/v2/shadersGlyph.ts` | 142 | - |
| `src/components/jarvis/v2/shadersRing.ts` | 289 | - |
| `src/components/jarvis/v2/shadersShard.ts` | 135 | - |
| `src/components/knowledge/KnowledgeView.tsx` | 631 | `eraseKnowledgeAsset`, `knowledgeAsset`, `knowledgeAssets`, `knowledgeOriginal`, `knowledgeSearch`, `uploadKnowledge` |
| `src/components/knowledge/RemembersTab.tsx` | 170 | `memoryFacts`, `memoryForget` |
| `src/components/onboarding/BrandLockup.tsx` | 17 | - |
| `src/components/onboarding/CompanionCarousel.tsx` | 160 | - |
| `src/components/onboarding/CompanionStep.tsx` | 87 | - |
| `src/components/onboarding/NameStep.tsx` | 32 | - |
| `src/components/onboarding/OnboardingGate.tsx` | 381 | `meSettings` |
| `src/components/onboarding/ProviderStep.tsx` | 293 | - |
| `src/components/onboarding/ReadyStep.tsx` | 49 | - |
| `src/components/onboarding/SearchablePicker.tsx` | 236 | - |
| `src/components/onboarding/SkinPicker.tsx` | 44 | - |
| `src/components/onboarding/StepHeading.tsx` | 19 | - |
| `src/components/onboarding/StepSkeleton.tsx` | 20 | - |
| `src/components/onboarding/VisionStep.tsx` | 26 | - |
| `src/components/onboarding/VoiceStep.tsx` | 145 | - |
| `src/components/onboarding/companionCatalogue.ts` | 68 | - |
| `src/components/onboarding/companionVoicePreview.ts` | 82 | - |
| `src/components/onboarding/onboardingActionState.ts` | 42 | - |
| `src/components/onboarding/previewAudioSignal.ts` | 128 | - |
| `src/components/onboarding/providerCatalogue.ts` | 125 | - |
| `src/components/onboarding/useCompanionPreview.ts` | 173 | - |
| `src/components/onboarding/useOnboardingCompletion.ts` | 48 | `putMeSettings`, `updateMeProfile` |
| `src/components/onboarding/useProviderSetup.ts` | 302 | `activateAiKey`, `aiKeys`, `approveAiKeyProposal`, `chatModelChoices` |
| `src/components/onboarding/useVoiceSetup.ts` | 175 | `integrationCatalogue`, `integrationConnections`, `submitIntegrationSecret` |
| `src/components/onboarding/voiceProviderCatalogue.ts` | 62 | - |
| `src/components/routine/RoutineCanvas.tsx` | 755 | - |
| `src/components/routine/RoutineV1Editor.tsx` | 149 | - |
| `src/components/routine/StepInspector.tsx` | 670 | - |
| `src/components/routine/graphChecks.ts` | 258 | - |
| `src/components/routine/predicates.ts` | 306 | - |
| `src/components/routine/routineV1.ts` | 177 | `scheduleWorkflow`, `triggerWorkflow`, `unscheduleWorkflow`, `upsertWorkflow` |
| `src/components/routine/useRoutineV1Controller.ts` | 206 | `workflow`, `workflows` |
| `src/components/settings/ArchivedSection.tsx` | 96 | `conversations`, `restoreMyConversation` |
| `src/components/settings/BehaviourSection.tsx` | 52 | - |
| `src/components/settings/CompactSections.tsx` | 622 | `currentOrg`, `logout`, `meNotifications`, `meSettings`, `putMeSettings`, `workspaces` |
| `src/components/settings/CompanionRows.tsx` | 137 | `resetEmotion` |
| `src/components/settings/HealthSection.tsx` | 222 | `budgets`, `health`, `hitl`, `readiness` |
| `src/components/settings/KnowledgeToggle.tsx` | 157 | `knowledgeProviders`, `setKnowledgeProvider` |
| `src/components/settings/LocalRuntimeSection.tsx` | 154 | - |
| `src/components/settings/ModelSettingsPanels.tsx` | 365 | - |
| `src/components/settings/ModelSettingsSection.tsx` | 517 | `bifrostModels`, `chatModelChoices`, `invoke`, `modelEndpoint`, `modelEndpoints`, `restoreModelEndpoint`, `retireModelEndpoint` |
| `src/components/settings/OperationsSettingsSection.tsx` | 18 | - |
| `src/components/settings/OvernightSection.tsx` | 207 | `auditSearch`, `hitl` |
| `src/components/settings/OvernightToggle.tsx` | 40 | - |
| `src/components/settings/ReadRepliesSetting.tsx` | 74 | `meSettings`, `putMeSettings` |
| `src/components/settings/SearchResults.tsx` | 68 | - |
| `src/components/settings/SectionHead.tsx` | 15 | - |
| `src/components/settings/SensingSection.tsx` | 150 | `sensing` |
| `src/components/settings/SensingSettingsGroups.tsx` | 299 | `deleteSensingEnrollment`, `putSensingCamera`, `putSensingPresence` |
| `src/components/settings/ShortcutsSection.tsx` | 63 | - |
| `src/components/settings/SpendingSection.tsx` | 187 | `budgets`, `cost` |
| `src/components/settings/companionSave.ts` | 54 | `characterAdopted`, `putMeSettings` |
| `src/components/settings/devDetails.ts` | 82 | `meSettings`, `putMeSettings` |
| `src/components/settings/format.ts` | 36 | - |
| `src/components/settings/healthCheckCopy.ts` | 47 | - |
| `src/components/settings/modelSettingsTypes.ts` | 43 | - |
| `src/components/settings/rowKit.tsx` | 266 | - |
| `src/components/settings/searchRegistry.ts` | 120 | - |
| `src/components/settings/useOvernightBehaviour.ts` | 114 | `currentOrg`, `updateCurrentOrg` |
| `src/components/shell/AppFrame.tsx` | 111 | - |
| `src/components/shell/AppRouteSurface.tsx` | 162 | - |
| `src/components/shell/CompanionSwitcher.tsx` | 158 | `putMeSettings` |
| `src/components/shell/ShellIcon.tsx` | 140 | - |
| `src/components/shell/ShellNav.tsx` | 72 | - |
| `src/components/shell/TaskList.tsx` | 319 | - |
| `src/components/shell/shellPreferences.ts` | 136 | - |
| `src/components/shell/useAppNavigation.ts` | 120 | - |
| `src/components/shell/useCompactNavigation.ts` | 137 | - |
| `src/components/shell/useConversationDirectory.ts` | 139 | `conversations`, `conversationsPage` |
| `src/components/shell/useDirectoryMetadata.ts` | 30 | `namedAgents`, `workspaces` |
| `src/components/shell/useTaskListModel.ts` | 163 | `deleteMyConversation`, `moveConversationProject`, `switchActiveContext` |
| `src/components/statusClass.ts` | 13 | - |
| `src/components/ultron/UltronRenderer.ts` | 322 | - |
| `src/components/ultron/UltronStage.tsx` | 90 | - |
| `src/components/ultron/UltronState.ts` | 85 | - |
| `src/components/ultron/shadersDendrite.ts` | 255 | - |
| `src/components/ultron/shadersUltron.ts` | 385 | - |
| `src/components/ultron/ultronDrive.ts` | 86 | - |
| `src/components/ultron/ultronPasses.ts` | 309 | - |
| `src/components/ultron/ultronScenePasses.ts` | 167 | - |
| `src/components/voice/VoiceCallScreen.tsx` | 168 | - |
| `src/components/voiceBargeIn.ts` | 375 | - |
| `src/components/voiceBargeInGraph.ts` | 288 | - |
| `src/components/voiceLoudness.ts` | 173 | - |
| `src/components/voiceMedia.ts` | 44 | - |
| `src/components/voiceSelfTrigger.ts` | 248 | - |
| `src/components/voiceSpectrum.ts` | 171 | - |
| `src/components/voiceStageInput.ts` | 64 | - |
| `src/components/voiceTone.ts` | 262 | - |
| `src/components/workerIdentityRefresh.ts` | 26 | - |
| `src/desktop.ts` | 372 | - |
| `src/desktopApiTransport.ts` | 155 | - |
| `src/desktopCamera.ts` | 84 | - |
| `src/desktopDownload.ts` | 20 | - |
| `src/desktopTrust.ts` | 30 | `startDeviceEnrollment` |
| `src/familiarIsland/islandHost.ts` | 263 | - |
| `src/familiarIsland/islandState.ts` | 202 | - |
| `src/familiarIsland/main.ts` | 65 | - |
| `src/localAgentClient.ts` | 380 | - |
| `src/main.tsx` | 37 | - |
| `src/onboarding.ts` | 18 | - |
| `src/productName.ts` | 94 | `branding` |
| `src/routes.ts` | 69 | - |
| `src/settingsSections.ts` | 169 | - |
| `src/shortcuts.ts` | 108 | - |
| `src/theme.ts` | 232 | - |
| `src/useMediaQuery.ts` | 30 | - |
| `src/useRouteSelection.ts` | 30 | - |
| `src/workflowDraft.ts` | 492 | - |

## Table C: SDK client methods no module under `apps/worker/src` calls

`sdks/web/src/client.ts` declares 256 public methods. `apps/worker/src` calls 248
of them. The remainder:

| SDK method | note |
|---|---|
| `artifact` | detail read; the Worker lists via `artifacts` and downloads via `downloadArtifact` |
| `artifactDownloadUrl` | URL builder, used internally by the SDK's own `downloadArtifact` |
| `getCall` | single-call read; the Worker uses `currentCall` and `calls` |
| `modelProfiles` | the older coarse voice-model projection, superseded by `chatModelChoices` |
| `refreshCallMedia` | media-bearer refresh; the Worker reconnects through `reopenCall` instead |
| `requestDeviceFileListLease` | device file listing; no Worker surface requests one |
| `searchConversations` | conversation search; deliberately absent from the sidebar and asserted absent by a test |
| `spawn` | direct subagent spawn; the Worker never spawns outside a chat turn |

## Table D: modules with no importer inside `apps/worker/src`

| module | lines | reached from | verdict |
|---|---:|---|---|
| `src/characterPlugins.ts` | 20 | `src/main.tsx` line 8, `import "./characterPlugins";` | side-effect entry, not an orphan |
| `src/components/AccountView.tsx` | 98 | `tests/accountOrganisationViews.test.tsx` | tested, never mounted |
| `src/components/AutomationView.tsx` | 2870 | `tests/inboxAutomationHonesty.test.tsx`, `tests/resourceDeepLinks.test.tsx`, `tests/parityViews.test.tsx` | tested, never mounted |
| `src/components/CameraDiscoverySettings.tsx` | 118 | nothing | no reference anywhere in `apps/worker` |
| `src/components/ConversationControls.tsx` | 167 | `tests/accountOrganisationViews.test.tsx`, and asserted on as source text by `tests/security/test_worker_surface_boundary.py` | tested, never mounted |
| `src/components/InboxHitl.tsx` | 354 | `tests/inboxHitl.test.tsx`, `tests/inboxAutomationHonesty.test.tsx` | tested, never mounted |
| `src/components/chat/RunSectionView.test.tsx` | 196 | vitest | in-tree test file |
| `src/components/chat/SubagentTabs.test.tsx` | 138 | vitest | in-tree test file |
| `src/components/chat/TaskInspector.test.tsx` | 360 | vitest | in-tree test file |
| `src/components/chat/useChatProjection.test.ts` | 65 | vitest | in-tree test file |
| `src/components/chat/useTranscriptViewport.test.tsx` | 323 | vitest | in-tree test file |
| `src/components/jarvis/JarvisGauge.ts` | 50 | `tests/jarvisGauge.test.ts` | tested, never mounted |
| `src/components/settings/OvernightSection.tsx` | 207 | nothing; `settings/OvernightToggle.tsx` is what `BehaviourSection.tsx` renders | no reference anywhere in `apps/worker` |
| `src/components/voiceTone.ts` | 262 | `tests/voiceTone.test.ts`, `tests/voiceChain.test.ts` | tested, never mounted |
| `src/familiarIsland/main.ts` | 65 | `familiar-island/vite.config.ts`, a second Vite build | separate entry point |

Bound: `rg -n "<basename>" apps/worker -g '!node_modules'` was run per row on
2026-08-24 against the pinned tree; the `reached from` column reports every hit
outside the module itself.
