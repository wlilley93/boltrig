import { useRef } from "react";

export function useDeckRefs(activeKey: string) {
  const deckRef = useRef<HTMLDivElement>(null);
  const planeRef = useRef<HTMLDivElement>(null);
  const frames = useRef(new Map<string, HTMLDivElement>());
  const visited = useRef(new Set<string>());
  // idempotent grow-only set: safe under StrictMode's double render
  visited.current.add(activeKey);

  return { deckRef, planeRef, frames, visited };
}
