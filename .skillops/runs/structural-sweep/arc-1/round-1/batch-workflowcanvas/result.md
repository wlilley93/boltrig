# Round 1 structural sweep result: WorkflowCanvas

## Branch

`structural/workflowcanvas-round1`

## Verification

- `pnpm run typecheck`: passed
- `pnpm run test:run`: 15 test files, 30 tests passed

The happy-dom `AbortError` printed to stderr is expected cleanup noise and does not fail tests.

## Commit range

`0c7abac`..`61b8087`

- `0c7abac` structural(workflowCanvas): extract graph model
- `4253b34` structural(workflowCanvas): extract node views
- `9717c0b` structural(workflowCanvas): extract canvas hooks
- `4e84057` structural(workflowCanvas): extract canvas view panels
- `79bf523` structural(workflowCanvas): extract orchestrator
- `61b8087` structural(workflowCanvas): update characterization test

## File outcomes

| File | LOC | Function count | Notes |
|---|---|---|---|
| `src/panels/WorkflowCanvas.tsx` (before) | 1046 | 1 huge component | exceeded all floors |
| `src/panels/WorkflowCanvas.tsx` (after) | 102 | 1 | thin orchestrator, re-exports public API |
| `src/panels/workflowCanvas/types.ts` | 42 | n/a | pure type module |
| `src/panels/workflowCanvas/graph.ts` | 145 | 6 | `deriveKind`, `isStepNode`, `graphToSteps`, `stepsToGraph`, `extractSteps`, `topoOrder` |
| `src/panels/workflowCanvas/nodes.tsx` | 47 | 3 | `StepNodeView`, `TriggerNodeView`, `nodeTypes` |
| `src/panels/workflowCanvas/useWorkflowData.ts` | 14 | 1 | fetching workflows + capabilities |
| `src/panels/workflowCanvas/useWorkflowMeta.ts` | 49 | 1 | save/run metadata state |
| `src/panels/workflowCanvas/useWorkflowGraph.ts` | 184 | 8 | node/edge state and graph mutations |
| `src/panels/workflowCanvas/useWorkflowInspector.ts` | 172 | 5 | inspector field state and actions |
| `src/panels/workflowCanvas/useWorkflowApi.ts` | 149 | 5 | `pickWorkflow`, `save`, `run`, `openRunCanvas`, hook wrapper |
| `src/panels/workflowCanvas/useWorkflowCanvas.ts` | 60 | 1 | composition hook, route effect, dirty guards |
| `src/panels/workflowCanvas/MetaForm.tsx` | 112 | 1 | metadata form |
| `src/panels/workflowCanvas/VerbPalette.tsx` | 57 | 1 | verb palette |
| `src/panels/workflowCanvas/TriggerPalette.tsx` | 28 | 1 | trigger buttons |
| `src/panels/workflowCanvas/WorkflowList.tsx` | 46 | 1 | workflow list |
| `src/panels/workflowCanvas/LoadPanel.tsx` | 29 | 1 | JSON load panel |
| `src/panels/workflowCanvas/StepInspector.tsx` | 144 | 2 | `safeObj`, `StepInspector` |
| `src/panels/workflowCanvas/StepsPreview.tsx` | 19 | 1 | serialised steps preview |
| `src/panels/workflowCanvas/RunRecord.tsx` | 51 | 1 | run result display |
| `tests/__characterization__/panels/WorkflowCanvas.test.tsx` (before) | 63 | - | - |
| `tests/__characterization__/panels/WorkflowCanvas.test.tsx` (after) | 76 | - | added `graphToSteps` round-trip test; `VerbInfo` import fixed to `@/api/types` |

Every file is under the 400 LOC floor. Every function is under the 80 LOC floor. Nesting depth, cyclomatic complexity, and parameter counts all stay within the floor. No mixed-concern violations remain: graph logic, node rendering, fetching, UI panels, and orchestration each live in separate files.

## Public API risk summary

Risk: **low**.

`src/panels/WorkflowCanvas.tsx` re-exports the same public symbols with the same signatures:

- `WorkflowCanvas` component
- `deriveKind`, `extractSteps`, `stepsToGraph` functions
- `nodeTypes` value
- `WorkflowStep`, `CanvasNode`, `StepNode`, `StepNodeData`, `RunNodeStatus` types

The only consumer-visible change is a corrected import in the characterization test: `VerbInfo` was previously imported from `@/panels/WorkflowCanvas` even though it was never exported; the test now imports it from `@/api/types`. TypeScript now passes the test file (via editor/vitest type resolution) and runtime behavior is unchanged.

`WorkflowRunCanvas.tsx` and `studio/WorkflowStudio.tsx` continue to import from `../WorkflowCanvas` and require no changes. All tests pass.
