import { DeckChevrons } from "@/deck/DeckChevrons";
import { DeckMiniMap } from "@/deck/DeckMiniMap";
import { DeckSlide } from "@/deck/DeckSlide";
import { useDeckAnnounce } from "@/deck/hooks/useDeckAnnounce";
import { useDeckMountPolicy } from "@/deck/hooks/useDeckMountPolicy";
import { useDeckNavigation } from "@/deck/hooks/useDeckNavigation";
import { useDeckSwipe } from "@/deck/hooks/useDeckSwipe";
import { useDeckRefs } from "@/deck/hooks/useDeckRefs";
import { useDeckTransition } from "@/deck/hooks/useDeckTransition";
import { cellKey, findCell, type DeckProps } from "@/deck/types";

export type { DeckCol, DeckRow, DeckProps } from "@/deck/types";

export function Deck(props: DeckProps): JSX.Element {
  const { rows, active, render, keepAlive } = props;
  const activeKey = cellKey(active.rowId, active.colKey);
  const target = findCell(rows, activeKey);
  const tx = target ? target.x : 0;
  const ty = target ? target.y : 0;

  const { deckRef, planeRef, frames, visited } = useDeckRefs(activeKey);
  const { moving, settledKey, bump } = useDeckTransition({
    rows,
    activeKey,
    tx,
    ty,
    planeRef,
    deckRef,
    frames,
  });
  const { tryMove } = useDeckNavigation(rows, activeKey, bump);
  const { onPointerDown, onPointerMove, onPointerUp, onPointerCancel } = useDeckSwipe(tryMove);
  const { mountedKeys, neighbourKeys } = useDeckMountPolicy(
    rows,
    activeKey,
    settledKey,
    keepAlive,
    visited,
  );
  const announce = useDeckAnnounce(rows, settledKey);

  const slides: JSX.Element[] = [];
  for (const key of mountedKeys) {
    const pos = findCell(rows, key);
    if (!pos) continue;
    const isActive = key === activeKey;
    const isNeighbour = !isActive && neighbourKeys.has(key);
    const isOutgoing = moving && key === settledKey && !isActive;
    const parked = !isActive && !isNeighbour && !isOutgoing;
    slides.push(
      <DeckSlide
        key={key}
        x={pos.x}
        y={pos.y}
        row={pos.row}
        col={pos.col}
        active={isActive}
        neighbour={isNeighbour}
        parked={parked}
        outgoingHold={isOutgoing}
        frameRef={(el) => {
          if (el) frames.current.set(key, el);
          else frames.current.delete(key);
        }}
      >
        {render(pos.row.id, pos.col.key)}
      </DeckSlide>,
    );
  }

  return (
    <div
      ref={deckRef}
      className={`deck${moving ? " deck--moving" : ""}`}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerCancel}
    >
      <div ref={planeRef} className="deck__plane">
        {slides}
      </div>

      <DeckChevrons rows={rows} activeKey={activeKey} />

      {/* The minimap is a transient position aid: mounted ONLY while a move is
          in flight, so it never sits over the chat composer or Agents cards at
          rest (the sidebar rail + breadcrumb convey position there). It is
          non-interactive (pointer-events:none); the rail drives navigation. */}
      {moving && <DeckMiniMap rows={rows} active={active} />}

      {/* outside the plane so a transform never re-roots it; announces settles */}
      <div className="deck__announcer" aria-live="polite">
        {announce}
      </div>
    </div>
  );
}
