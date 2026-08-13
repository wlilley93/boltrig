// Boltrig UI SDK (web) - the framework-agnostic streaming CONTRACT every boltrig
// frontend shares so they render IDENTICAL chat/run data (SDK-CONTRACT sec 4,
// GAP G6). The Worker consumes the contract from this package
// (`sdks/web/src/types.ts`, `chatTurnNormalizer.ts` and `chatTurnTypes.ts`):
// the ChatEvent frame union, the NormalizedTurn model, and the normalizeEvents
// reducer. Transport (fetch/SSE/identity) stays app-side by design - each app
// brings its own; the shared contract is the frame vocabulary + the reducer.
export * from "./types.js";
export * from "./capabilityInvocation.js";
export * from "./chatTurnTypes.js";
export { normalizeEvents } from "./chatTurnNormalizer.js";
export {
  BoltrigApiError,
  BoltrigClient,
  pumpSse,
} from "./client.js";
export type {
  BoltrigClientOptions,
  ChatFollowResult,
  ChatQueued,
} from "./client.js";
export { WORKER_INTEGRATION_CATALOGUE } from "./integrationCatalogue.js";
export {
  RESTING_FAMILIAR_STATE_V2,
  sanitizeFamiliarState,
} from "./familiarState.js";
export type {
  FamiliarActivityMode,
  FamiliarPhenotypeResponse,
  FamiliarPhenotypeScalar,
  FamiliarGesture,
  FamiliarGazeSource,
  FamiliarPhenotypeV2,
  FamiliarPresentationModeV2,
  FamiliarStateV2,
  FamiliarVoiceBands,
} from "./familiarState.js";
export {
  characterRegistryRevision,
  characterFor,
  isCharacterId,
  isCharacterRegistered,
  listCharacters,
  registerCharacter,
  subscribeCharacters,
} from "./characters.js";
export {
  CHARACTER_BUNDLE_SCHEMA_VERSION,
  CharacterBundleError,
  bundleReadsPhenotype,
  bundleWantsBudgets,
  bundleWantsCamera,
  bundleWantsPresence,
  exportCharacterBundle,
  parseCharacterBundle,
} from "./characterBundle.js";
export type {
  CharacterBundleAssetRef,
  CharacterBundleExportOptions,
  CharacterBundleCapabilities,
  CharacterBundleCompanionVisual,
  CharacterBundleEmotion,
  CharacterBundleManifest,
  CharacterBundlePhenotype,
  CharacterBundlePrompts,
  CharacterBundleShaderVisual,
  CharacterBundleType,
  CharacterBundleVisual,
} from "./characterBundle.js";
export type {
  Character,
  CharacterId,
  CharacterPresentationMode,
  CharacterRenderProps,
  CharacterStageState,
  CharacterTurnInput,
  PhenotypeResponse,
  PresentationMode,
  SensingDecision,
  StageRenderProps,
  StageState,
  StageTurnInput,
} from "./characters.js";
