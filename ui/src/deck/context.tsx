// Per-slide visibility context. Each deck slide wraps its content in a
// DeckSlideContext.Provider so panels can quiesce polling / live regions while
// their slide is parked or merely a pre-mounted neighbour. The default is
// { active: true } so any panel rendered OUTSIDE the deck behaves exactly as
// it did before the deck existed.

import { createContext, useContext } from "react";

export interface SlideState {
  active: boolean;
  neighbour: boolean;
}

export const DeckSlideContext = createContext<SlideState>({
  active: true,
  neighbour: false,
});

export function useSlideActive(): boolean {
  return useContext(DeckSlideContext).active;
}
