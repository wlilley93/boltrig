# 0004 - The spatial deck frontend

Date: 2026-07-02. Status: adopted (Principal-directed product design; engineering
disposition recorded here). Supersedes nothing; extends the R9 front-end experience
spec's presentation layer.

## The instruction

The Principal specified the console's main area as a 2D field of full-screen bordered
"slides" navigated up/down and left/right beside the existing sidebar: chat at the top
left; an agent-builder org chart below it with one slide per agent to the right; an
automations row below that with one slide per workflow node (plus insert/append
affordances); settings below that. The product direction is the Principal's; this
record captures how it is made real and which engineering calls were taken.

## The mechanics

The hash route stays the single source of truth; the deck is a projection of the route
tree onto a plane. Rows are zones (chat, agents, automations, settings, ops), column 0
is a row's anchor, columns to the right are its detail pages. A translate3d container
moves between cells; slides are their own scrollers; navigation is by explicit
affordances only (sidebar map, edge chevrons, Ctrl/Cmd+Alt+Arrow, minimap, guarded
touch swipe) - never wheel/scroll hijack, because slides scroll and pan internally.

## Decisive calls (reversible; recorded per AGENTS.md working style)

1. Router extended with a full `segs` array; `basePath()` rebuilds the whole path so
   the `?run=` drawer stays orthogonal at any depth. Old two-segment grammar intact.
2. Detail slides are keyed by id (agent name, workflow step id), never by ordinal:
   topological order legally changes under edits, and step ids anchor run checkpoints
   and durable boundaries, so coordinates derive from ids at render time.
3. The eleven ops tabs collapse into ONE ops row with columns (anchor = home) rather
   than eleven rows; every existing `#/<tab>` route keeps working. Approvals gets a
   pending-count badge in the sidebar so the watch plane stays discoverable.
4. Default landing moves from `#/home` to `#/chat` (the Principal's stated top-left).
5. Keyboard chord is Ctrl/Cmd+Alt+Arrow; bare Alt+Arrow collides with browser history
   and macOS caret movement, and is left to the platform.
6. Adjacent-cell moves slide; longer or diagonal jumps cross-fade (no travel across
   unmounted cells; caps vestibular motion). Reduced-motion collapses both to instant
   via the existing global rules.
7. Mounted set = active + orthogonal neighbours + keep-alive (chat once visited, so an
   in-flight SSE stream survives off-screen; hidden keep-alive slides are
   visibility:hidden + inert). `useFetch` gains a `paused` option and slides pause
   their polling off-screen: keep-alive means state preserved, network quiesced.
8. Per-slide Suspense and ErrorBoundary (one crashing or lazy-loading slide can never
   blank the deck); the error card renders absolute within the slide because a
   transformed ancestor re-homes position:fixed.
9. Agents and automations rows are cosmetically gated to author roles (the hierarchy
   read is author/admin-gated server-side); the server 403 stays authoritative and is
   rendered faithfully.
10. No new dependency for the deck itself (CSS transforms; a slide/carousel library
    was considered and rejected - consolidation). Any markdown renderer for the chat
    upgrade is a separate recorded dependency call.
11. No new UI test framework this round: the repo's declared UI gate is a green
    typecheck+build; router logic is kept as pure functions to stay testable.

## Tensions with the R9 spec, disposed

R9's three-plane left-nav becomes the deck's zone map (the spec marks the plane
grouping presentation-only, App.tsx:52-53); the run spine stays cross-row because the
`?run=` drawer remains a global overlay that never moves the deck; the watch plane's
demotion is compensated by the approvals badge and home-as-ops-anchor. The typed
streaming contract (AGENTS.md) is untouched: slides render the same event vocabulary.
