import { useMemo } from "react";

import { findCell, mountNeighbours, type DeckRow } from "@/deck/types";

type MutableRefObject<T> = React.MutableRefObject<T>;

export function useDeckMountPolicy(
  rows: DeckRow[],
  activeKey: string,
  settledKey: string,
  keepAlive: string[] | undefined,
  visited: MutableRefObject<Set<string>>,
) {
  // Mount policy: active + settled + orthogonal neighbours of the SETTLED cell
  // (so new neighbours mount only after settle) + visited keep-alive cells.
  const neighbourKeys = useMemo(
    () => new Set(mountNeighbours(rows, settledKey)),
    [rows, settledKey],
  );

  const mountedKeys = useMemo(() => {
    const set = new Set<string>();
    const add = (k: string) => {
      if (findCell(rows, k)) set.add(k);
    };
    add(activeKey);
    add(settledKey);
    for (const k of neighbourKeys) add(k);
    for (const k of keepAlive ?? []) if (visited.current.has(k)) add(k);
    return set;
    // visited only grows, and every growth comes with a render of its own
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, activeKey, settledKey, neighbourKeys, keepAlive]);

  return { mountedKeys, neighbourKeys };
}
