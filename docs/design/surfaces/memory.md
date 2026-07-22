# Memory surface: ratified specification

Status: **ratified 2026-07-21**. Route: `#/memory`. This closes the Memory IA gate in the
Enhancement Charter.

## 1. Mental model

Memory is the assistant's scoped evidence shelf, not a document database. A person should be
able to find what the assistant knows, see why it knows it, teach it one fact, or load a source.
Every fact keeps its owner scope, data class, and provenance attached. A result without provenance
is incomplete UI.

The four task modes are fixed:

1. **Recall** asks a plain-language question and returns matching facts. This is the default.
2. **Browse** inspects scoped facts and performs deliberate fact or source erasure.
3. **Remember** teaches one screened fact with optional provenance and relationships.
4. **Ingest** screens and loads a multi-item source, then shows ingestion history.

The modes are an in-slide task switch, not new deck columns. The deck row remains stable while a
person moves between memory tasks.

## 2. The 80% path

Ask a question in Recall, choose Connections or Similarity, and press **Search**. Search is the
only primary control in the default state. Results render as fact cards with content, fact id,
scope, data class, source kind, source reference, timestamp, and graph path when present.

## 3. Interaction contract

- Recall uses a two-option segmented control and a bounded result-count stepper. A first search
  with no result renders a calm empty state, not an error.
- Browse filters by fact type. Erasing a fact or an exact source uses P27 ArmConfirm in-frame.
  The UI never uses amber for erasure because this route is destructive but not an HITL pause.
- Remember defaults type to Entity, sensitivity to Standard, and source type to Verb result.
  Scope and provenance stay in progressive disclosure. Sensitive selection shows the local-only
  residency warning before submit.
- Ingest accepts one passage per line. History headings use human labels while ids and source
  references stay mono. Screening counts and status are labelled, not raw field names.
- `binding_not_found` renders the canonical "Memory is not enabled for your org." callout.
- Every server denial is rendered faithfully. Empty scoped data never masquerades as denial.

## 4. State and accessibility contract

P24 precedence applies independently to each mode: denied, error, first-load skeleton, empty,
ready. Poll refreshes preserve visible data. Mode controls expose selected state and keyboard
focus. Fact status never relies on hue alone. All ids, scopes, and source references use mono.
The surface must survive compact density, light theme, high contrast, and reduced motion.

## 5. Chat parity

| UI action | Verb path | Chat phrasing | Status |
|---|---|---|---|
| Recall memory | `memory.recall` | "What do we remember about Priya's accounts?" | exists |
| Remember fact | `memory.remember` | "Remember that Priya owns the Acme account." | exists |
| Ingest source | screened ingestion orchestration, then `memory.remember` per accepted item | "Load these launch notes into memory from document launch-plan-v3." | exists |
| Forget fact or source | `memory.forget` | "Forget everything derived from document launch-plan-v3." | exists |
| Browse facts and ingestions | shared `GET /v1/memory/*` reads | "Show the facts in my scope and where they came from." | exists |

Remember and Ingest expose N16 ByChat using current form state. Destructive erasure keeps its
deliberate local confirmation in the console; chat invokes the same governed memory verb.

## 6. Acceptance

- Recall is the default and has exactly one primary control.
- Every rendered fact shows provenance and scope.
- Sensitive memory is clearly labelled local-only before it is written.
- Forget always requires an in-frame deliberate confirmation.
- No primary control is raw JSON.
- All four tasks share one coherent surface and one memory verb-space.

## 7. Knowledge boundary

Memory remains the assistant's scoped evidence shelf. It must not expand into a
file vault, document catalogue, or universal search surface.

The first-party Knowledge extension owns originals, assets, immutable
revisions, representations, stable segments, document search, and typed context
packages. Memory may cite that evidence and may be recalled alongside it, but it
does not replace it. See
`docs/proposals/codex-native-knowledge-extension.md`.

The first text, Markdown, and PDF slice is shipped at `#/knowledge`; later
multimodal and connector phases remain explicitly out of scope. See
`docs/design/surfaces/knowledge.md`.
