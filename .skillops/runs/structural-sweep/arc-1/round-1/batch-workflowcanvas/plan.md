# Round 1 structural sweep plan: WorkflowCanvas

## Scope

Decompose `ui/src/panels/WorkflowCanvas.tsx` (~1,046 LOC) into a `workflowCanvas/`
submodule so every resulting file satisfies the structural floor.

## Extraction units

1. **Graph model** (`workflowCanvas/types.ts`, `workflowCanvas/graph.ts`)
   - Pure step/node/edge data types.
   - Binding-driven kind derivation.
   - Bidirectional `stepsToGraph` / `graphToSteps` helpers.
   - `extractSteps` payload normaliser.

2. **Node views** (`workflowCanvas/nodes.tsx`)
   - `StepNodeView`, `TriggerNodeView`, and `nodeTypes` registry.

3. **Data hooks** (`workflowCanvas/useWorkflowData.ts`, `workflowCanvas/useWorkflowMeta.ts`)
   - API list/capability fetching.
   - Workflow metadata and run-result state.

4. **Graph hook** (`workflowCanvas/useWorkflowGraph.ts`)
   - React Flow node/edge state, selection, palette, JSON load, and node mutations.

5. **Inspector hook** (`workflowCanvas/useWorkflowInspector.ts`)
   - Inspector field state, dirty check, commit, rename, and verb swap.

6. **API actions hook** (`workflowCanvas/useWorkflowApi.ts`)
   - `pickWorkflow`, `save`, `run`, `openRunCanvas`.

7. **Composition hook** (`workflowCanvas/useWorkflowCanvas.ts`)
   - Wires the above hooks and adds route-driven selection + dirty-guarded navigation.

8. **View panels** (`workflowCanvas/MetaForm.tsx`, `VerbPalette.tsx`, `TriggerPalette.tsx`,
   `WorkflowList.tsx`, `LoadPanel.tsx`, `StepInspector.tsx`, `StepsPreview.tsx`,
   `RunRecord.tsx`)
   - Small presentational components, each under the function-line limit.

9. **Public orchestrator** (`panels/WorkflowCanvas.tsx`)
   - Thin composition component that re-exports the public API unchanged.

10. **Characterization test** (`tests/__characterization__/panels/WorkflowCanvas.test.tsx`)
    - Update imports; add a `graphToSteps` round-trip assertion.

## API preservation

`WorkflowCanvas.tsx` will re-export the following with the same signatures:

- `WorkflowCanvas` component
- `deriveKind`, `extractSteps`, `stepsToGraph` functions
- `nodeTypes` value
- `WorkflowStep`, `CanvasNode`, `StepNode`, `StepNodeData`, `RunNodeStatus` types

## Verification

- `pnpm run typecheck`
- `pnpm run test:run tests/__characterization__/panels/WorkflowCanvas.test.tsx`
- Push branch `structural/workflowcanvas-round1` without merging.
